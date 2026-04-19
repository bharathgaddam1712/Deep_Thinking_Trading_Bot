mod auth;
mod client;
mod utils;
mod market_data;
mod state;
mod risk_gate;

use utils::{BotError, ClockSync, Secret};
use client::AccountClient;
use state::GlobalState;
use risk_gate::RiskGate;
use dotenvy::dotenv;
use std::env;
use std::sync::Arc;
use bytes::BytesMut;
use tokio::sync::broadcast;
use tracing::{info, error};

fn main() {
    dotenv().ok();
    
    // Initialize tracing mechanism to enforce professional micro-latencies across log pipelines
    tracing_subscriber::fmt::init();
    
    let api_key = Secret::new(env::var("API_KEY").unwrap_or_else(|_| "MYAPIKEY".to_string()));
    let secret_key = Secret::new(env::var("SECRET_KEY").unwrap_or_else(|_| "MYAPISECRET".to_string()));

    info!("Bot Initializing..."); 
    
    let clock = ClockSync::new();
    
    let check_rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("Failed to build pre-flight runtime");

    info!("Executing SYNCHRONOUS PRE-FLIGHT HANDSHAKE...");
    // A persistent buffer memory pool initialized globally explicitly bypassing heap re-allocations
    let mut payload_buffer = BytesMut::with_capacity(4096);
    
    let (account_client, global_state) = check_rt.block_on(async {
        if let Err(e) = clock.sync_once_direct().await {
            match e {
                BotError::ClockDriftCritical => {
                    error!("FATAL: {:?}", e);
                    std::process::exit(1);
                }
                _ => {
                    error!("FATAL: Initial clock sync failed: {:?}", e);
                    std::process::exit(1);
                }
            }
        }

        info!("Clock drift synchronized seamlessly: {} ms", clock.drift());

        let client = match AccountClient::new(api_key, secret_key, clock.clone()) {
            Ok(c) => Arc::new(c),
            Err(e) => {
                error!("FATAL: Failed to init client: {:?}", e);
                std::process::exit(1);
            }
        };

        let global_state = Arc::new(GlobalState::new());

        // Fetch ExchangeInfo Configuration
        match client.get_exchange_info_raw(&mut payload_buffer).await {
            Ok(payload) => {
                 match AccountClient::parse_exchange_info(payload) {
                     Ok(info) => {
                         let mut cache = global_state.symbols.write().unwrap();
                         for (symbol_name, sym) in info.trade_pairs {
                             cache.insert(symbol_name, state::SymbolState {
                                 price_precision: sym.price_precision,
                                 amount_precision: sym.amount_precision,
                                 mini_order: sym.mini_order,
                             });
                         }
                     }
                     Err(e) => error!("Failed parsing exchange info: {:?}", e),
                 }
            }
            Err(e) => error!("Failed downloading exchange info: {:?}", e),
        }

        // Fetch Balance and Setup Initial Portfolio Limits
        match client.get_balance_raw(&mut payload_buffer).await {
            Ok(payload_slice) => {
                match AccountClient::parse_balance(payload_slice) {
                    Ok(balance) => {
                        info!("Initial Handshake Successful. Balance:\n***REDACTED***");
                        let mut initial_usd = 1000.0; // Fail-safe default
                        if let Some(wallet) = balance.wallet {
                            if let Some(usd_val) = wallet.get("USD").and_then(|v| v.as_f64()) {
                                initial_usd = usd_val;
                            }
                        }
                        global_state.set_balance(initial_usd);
                        info!("GlobalState Registered Starting Limit Base: ${:.2}", initial_usd);
                    }
                    Err(e) => {
                        error!("FATAL: Parsing handshake failed. {:?}", e);
                        std::process::exit(2);
                    }
                }
            }
            Err(e) => {
                error!("FATAL: Initialization connect failed. {:?}", e);
                std::process::exit(2);
            }
        }
        
        (client, global_state)
    });

    info!("Bot successfully stabilized. Transitioning HTTPS TCP pools seamlessly to MULTI-THREAD ASYNC strategy engine.");

    let multi_rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("Failed to build multi-thread runtime");

    let (shutdown_tx, _) = broadcast::channel(1);
    let shutdown_rx1 = shutdown_tx.subscribe();

    multi_rt.block_on(async move {
        // Continuous verification drift mechanism natively spawning off background tokio bounds
        clock.start_background_sync().await.unwrap();
        
        // Spawn Sprint 2 Market Data Engine natively wrapping ZeroMQ IPC bridges
        let market_data_client = account_client.clone();
        let market_data_task = tokio::spawn(market_data::start_market_data_engine(
            clock.clone(), 
            market_data_client, 
            shutdown_rx1
        ));
        
        // Sprint 4: The Synchronous Risk Gate Thread
        let risk_gate = Arc::new(RiskGate::new(global_state.clone()));
        let rg_clone = risk_gate.clone();
        
        std::thread::spawn(move || {
            let zmq_ctx = zmq::Context::new();
            let pull_socket = zmq_ctx.socket(zmq::PULL).expect("FATAL: Failed to init RiskGate ZMQ PULL");
            
            // Connect to Python Strategy Engine bound TCP port
            pull_socket.connect("tcp://127.0.0.1:5557").expect("FATAL: RiskGate PULL connect failed");
            info!("Risk Gate PULL socket connected to tcp://127.0.0.1:5557");

            loop {
                if let Ok(raw_msg) = pull_socket.recv_bytes(0) {
                    use prost::Message;
                    use crate::market_data::trading::TradeSignal;
                    
                    if let Ok(signal) = TradeSignal::decode(&*raw_msg) {
                        match rg_clone.validate(&signal) {
                            Ok(valid_order) => {
                                info!("RiskGate PASS => {:?}", valid_order);
                                // Await Execution Engine Sprint 5 payload dispatch here
                            }
                            Err(e) => {
                                error!("RiskGate REJECTED => {:?}", e);
                            }
                        }
                    }
                }
            }
        });

        // Wait gracefully for strategy suspension hooks locking active bounds reliably
        if tokio::signal::ctrl_c().await.is_ok() {
            info!("Graceful Shutdown Sequence Initiated. Distributing signals.");
            let _ = shutdown_tx.send(());
        }
        
        let _ = market_data_task.await;
        
        info!("Strategy Engine Terminated Cleanly.");
    });
}
