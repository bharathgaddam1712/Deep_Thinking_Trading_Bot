use crate::auth::{OrderedParams, Signer};
use crate::utils::{BotError, ClockSync, Secret};
use reqwest::{Client, ClientBuilder, StatusCode};
use std::time::Duration;
use std::collections::HashMap;
use std::borrow::Cow;
use bytes::BytesMut;

#[derive(serde::Deserialize, Debug)]
#[allow(dead_code)]
pub struct ZeroCopyBalanceResponse<'a> {
    #[serde(rename = "Success")]
    pub success: bool,
    #[serde(rename = "ErrMsg", borrow)]
    pub err_msg: Cow<'a, str>,
    #[serde(rename = "Wallet")]
    pub wallet: Option<serde_json::Value>, 
}

#[derive(serde::Deserialize, Debug)]
#[allow(dead_code)]
pub struct ZeroCopyExchangeInfo<'a> {
    /// Not present in exchangeInfo response (only in order responses); defaults to true
    #[serde(rename = "Success", default = "bool_true")]
    pub success: bool,
    #[serde(rename = "ErrMsg", borrow, default)]
    pub err_msg: Cow<'a, str>,
    /// Map of symbol name (e.g. "BTC/USD") to its symbol info
    #[serde(rename = "TradePairs")]
    pub trade_pairs: HashMap<String, ZeroCopySymbolInfo<'a>>,
}

/// Per-symbol metadata as returned by the TradePairs map value
#[derive(serde::Deserialize, Debug)]
#[allow(dead_code)]
pub struct ZeroCopySymbolInfo<'a> {
    #[serde(rename = "Coin", borrow)]
    pub coin: Cow<'a, str>,
    #[serde(rename = "PricePrecision")]
    pub price_precision: u32,
    #[serde(rename = "AmountPrecision")]
    pub amount_precision: u32,
    #[serde(rename = "MiniOrder")]
    pub mini_order: f64,
}

/// serde default helper: returns true
fn bool_true() -> bool { true }

pub struct AccountClient {
    client: Client,
    clock: ClockSync,
    signer: Signer,
}

impl AccountClient {
    pub fn new(api_key: Secret<String>, secret_key: Secret<String>, clock: ClockSync) -> Result<Self, BotError> {
        let client = ClientBuilder::new()
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(10))
            .tcp_nodelay(true)
            .pool_max_idle_per_host(1) // explicitly set connecting behavior
            .build()
            .map_err(|e| BotError::Other(e.to_string()))?;
            
        Ok(Self {
            client,
            clock,
            signer: Signer::new(secret_key, api_key),
        })
    }

    pub async fn get_balance_raw<'a>(&self, response_buffer: &'a mut BytesMut) -> Result<&'a [u8], BotError> {
        let mut params = OrderedParams::new();
        let ts = self.clock.get_synced_timestamp().to_string();
        params.insert("timestamp", Cow::Owned(ts));

        let mut buffer = BytesMut::with_capacity(128);
        params.build_query_string(&mut buffer);
        let req = self.signer.prepare_request(&buffer);
        
        let url = format!("https://mock-api.roostoo.com/v3/balance?{}", req.query_string);

        let mut res = self.client.get(&url)
            .headers(req.headers)
            .send()
            .await?;
            
        let status = res.status();
        if status == StatusCode::TOO_MANY_REQUESTS {
            return Err(BotError::RateLimitExceeded);
        } else if status == StatusCode::UNAUTHORIZED || status == StatusCode::FORBIDDEN {
            let text = res.text().await.unwrap_or_default();
            return Err(BotError::AuthenticationFailed(text));
        } else if !status.is_success() {
            return Err(BotError::TransientNetwork(status.as_u16()));
        }

        // Buffer linearly extracted directly into reusable payload mapping
        response_buffer.clear();
        while let Some(chunk) = res.chunk().await? {
            response_buffer.extend_from_slice(&chunk);
        }
        
        Ok(response_buffer)
    }

    pub fn parse_balance<'a>(payload: &'a [u8]) -> Result<ZeroCopyBalanceResponse<'a>, BotError> {
        let parsed: ZeroCopyBalanceResponse<'a> = serde_json::from_slice(payload)
            .map_err(|e| BotError::Other(format!("Failed to parse JSON slice: {}", e)))?;
            
        if !parsed.success {
            return Err(BotError::AuthenticationFailed(parsed.err_msg.into_owned()));
        }
            
        Ok(parsed)
    }

    pub async fn get_exchange_info_raw<'a>(&self, response_buffer: &'a mut BytesMut) -> Result<&'a [u8], BotError> {
        let url = "https://mock-api.roostoo.com/v3/exchangeInfo";

        let mut res = self.client.get(url)
            .send()
            .await?;
            
        let status = res.status();
        if status == StatusCode::TOO_MANY_REQUESTS {
            return Err(BotError::RateLimitExceeded);
        } else if !status.is_success() {
            return Err(BotError::TransientNetwork(status.as_u16()));
        }

        // Buffer linearly extracted directly into reusable payload mapping
        response_buffer.clear();
        while let Some(chunk) = res.chunk().await? {
            response_buffer.extend_from_slice(&chunk);
        }
        
        Ok(response_buffer)
    }

    pub fn parse_exchange_info<'a>(payload: &'a [u8]) -> Result<ZeroCopyExchangeInfo<'a>, BotError> {
        let parsed: ZeroCopyExchangeInfo<'a> = serde_json::from_slice(payload)
            .map_err(|e| BotError::Other(format!("Failed to parse JSON slice: {}", e)))?;

        if parsed.trade_pairs.is_empty() {
            return Err(BotError::Other("ExchangeInfo returned empty TradePairs".to_string()));
        }

        Ok(parsed)
    }
}
