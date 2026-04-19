use crate::client::AccountClient;
use crate::utils::ClockSync;
use prost::Message;
use reqwest::Client;
use serde::Deserialize;
use std::borrow::Cow;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tracing::{debug, error, info, warn};

#[allow(dead_code)]
pub mod trading {
    include!(concat!(env!("OUT_DIR"), "/trading.rs"));
}

/// Response shape for GET /v3/ticker  (RCL_TSCheck — only needs `timestamp`, no HMAC)
#[derive(Deserialize, Debug)]
pub struct TickerResponse<'a> {
    #[serde(rename = "Success")]
    pub success: bool,
    #[serde(rename = "ErrMsg", borrow)]
    pub err_msg: Cow<'a, str>,
    #[serde(rename = "Data")]
    pub data: HashMap<Cow<'a, str>, TickerData>,
}

#[derive(Deserialize, Debug)]
pub struct TickerData {
    #[serde(rename = "LastPrice")]
    pub last_price: f64,
    #[serde(rename = "CoinTradeValue")]
    pub coin_trade_value: f64,
}

/// Polls `GET /v3/ticker` every `poll_interval` and forwards encoded protobuf
/// ticks to a ZMQ PUSH socket on `tcp://127.0.0.1:5556`.
///
/// ZMQ's `Socket` is `!Send`, so it lives on a dedicated OS thread. The async
/// polling loop hands encoded bytes over via a `std::sync::mpsc` channel.
pub async fn start_market_data_engine(
    clock: ClockSync,
    _client: Arc<AccountClient>,
    mut shutdown_rx: tokio::sync::broadcast::Receiver<()>,
) {
    // ── ZMQ thread ───────────────────────────────────────────────────────────
    // zmq::Socket is !Send — pin it to its own OS thread and communicate via
    // a bounded mpsc channel.
    let (zmq_tx, zmq_rx) = std::sync::mpsc::sync_channel::<Vec<u8>>(256);
    let (stop_tx, stop_rx) = std::sync::mpsc::channel::<()>();

    std::thread::spawn(move || {
        let zmq_ctx = zmq::Context::new();
        let push_socket = zmq_ctx
            .socket(zmq::PUSH)
            .expect("FATAL: Failed to init ZMQ PUSH socket");

        // tcp:// works on all platforms; ipc:// requires Unix /tmp paths
        push_socket
            .bind("tcp://127.0.0.1:5556")
            .expect("FATAL: Failed to bind ZMQ tcp socket on port 5556");

        info!("ZMQ PUSH socket bound on tcp://127.0.0.1:5556");

        loop {
            if stop_rx.try_recv().is_ok() {
                info!("ZMQ thread: stop signal received, exiting.");
                break;
            }
            match zmq_rx.recv_timeout(Duration::from_millis(100)) {
                Ok(payload) => {
                    if let Err(e) = push_socket.send(&*payload, zmq::DONTWAIT) {
                        if e == zmq::Error::EAGAIN {
                            // No PULL consumer connected yet — silently drop the tick.
                            // This is normal when the strategy engine hasn't started.
                        } else {
                            error!("ZMQ send failed: {}", e);
                        }
                    }
                }
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                    info!("ZMQ channel dropped, thread exiting.");
                    break;
                }
            }
        }
    });

    // ── REST polling loop ─────────────────────────────────────────────────────
    // The Roostoo mock exchange is REST-only; there is no WebSocket stream.
    // We poll GET /v3/ticker every POLL_INTERVAL and encode each tick as
    // a protobuf MarketTick message before forwarding it to the ZMQ thread.
    const POLL_INTERVAL: Duration = Duration::from_secs(1);
    const TICKER_URL: &str = "https://mock-api.roostoo.com/v3/ticker";

    let http = Client::builder()
        .timeout(Duration::from_secs(5))
        .tcp_nodelay(true)
        .build()
        .expect("FATAL: Failed to build HTTP client for market data engine");

    // Reusable JSON buffer to avoid repeated heap allocations
    let mut json_buf = String::with_capacity(4096);

    loop {
        tokio::select! {
            _ = shutdown_rx.recv() => {
                info!("Market Data Engine: shutdown received, stopping.");
                let _ = stop_tx.send(());
                break;
            }
            _ = tokio::time::sleep(POLL_INTERVAL) => {
                let ingress_ts = Instant::now();
                let ts = clock.get_synced_timestamp().to_string();

                let result = http
                    .get(TICKER_URL)
                    .query(&[("timestamp", ts.as_str())])
                    .send()
                    .await;

                match result {
                    Err(e) => {
                        warn!("Ticker HTTP request failed: {}", e);
                        continue;
                    }
                    Ok(resp) => {
                        if !resp.status().is_success() {
                            warn!("Ticker HTTP {}", resp.status());
                            continue;
                        }
                        match resp.text().await {
                            Err(e) => {
                                error!("Failed to read ticker body: {}", e);
                                continue;
                            }
                            Ok(text) => {
                                json_buf.clear();
                                json_buf.push_str(&text);

                                match serde_json::from_str::<TickerResponse>(&json_buf) {
                                    Err(e) => {
                                        error!("Failed to parse ticker JSON: {}", e);
                                        continue;
                                    }
                                    Ok(ticker) => {
                                        if !ticker.success {
                                            warn!("Ticker API error: {}", ticker.err_msg);
                                            continue;
                                        }

                                        let current_ms = clock.get_synced_timestamp().0;

                                        for (pair, data) in ticker.data {
                                            let tick = trading::MarketTick {
                                                pair: pair.into_owned(),
                                                price: data.last_price,
                                                volume: data.coin_trade_value,
                                                timestamp: current_ms,
                                            };

                                            let mut buf = bytes::BytesMut::with_capacity(
                                                tick.encoded_len(),
                                            );
                                            if tick.encode(&mut buf).is_ok() {
                                                if zmq_tx.try_send(buf.to_vec()).is_err() {
                                                    warn!("ZMQ channel full — dropping tick for backpressure.");
                                                }
                                            }
                                        }

                                        debug!("Poll cycle latency: {:?}", ingress_ts.elapsed());
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    info!("Market Data Engine terminated.");
}
