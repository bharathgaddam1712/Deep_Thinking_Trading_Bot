use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use std::fmt;
use tokio::time::{interval, Duration};
use reqwest::Client;
use serde::Deserialize;
use thiserror::Error;

// Type-Safe Newtype Timing
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct RoostooMs(pub u64);

impl fmt::Display for RoostooMs {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

#[derive(Error, Debug)]
pub enum BotError {
    #[error("Transient network error (Retryable): HTTP {0}")]
    TransientNetwork(u16),
    #[error("Authentication failed (Fatal): {0}")]
    AuthenticationFailed(String),
    #[error("Rate limit exceeded (Backoff)")]
    RateLimitExceeded,
    #[error("Clock drift critical threshold exceeded")]
    ClockDriftCritical,
    #[error("Risk Gate Validation Error: {0}")]
    RiskManagement(String),
    #[error("Other error: {0}")]
    Other(String),
}

impl From<reqwest::Error> for BotError {
    fn from(err: reqwest::Error) -> Self {
        if let Some(status) = err.status() {
            if status == reqwest::StatusCode::TOO_MANY_REQUESTS {
                return BotError::RateLimitExceeded;
            } else if status == reqwest::StatusCode::UNAUTHORIZED || status == reqwest::StatusCode::FORBIDDEN {
                return BotError::AuthenticationFailed(err.to_string());
            }
            return BotError::TransientNetwork(status.as_u16());
        }
        BotError::Other(err.to_string())
    }
}

#[derive(Clone)]
pub struct Secret<T>(T);

impl<T> Secret<T> {
    pub fn new(val: T) -> Self { Self(val) }
    pub fn inner(&self) -> &T { &self.0 }
}

impl<T> fmt::Debug for Secret<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "***REDACTED***")
    }
}

impl<T> fmt::Display for Secret<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "***REDACTED***")
    }
}

#[derive(Clone)]
pub struct ClockSync {
    drift: Arc<AtomicI64>,
}

#[derive(Deserialize)]
struct ServerTimeResponse {
    #[serde(rename = "ServerTime")]
    server_time: u64,
}

impl ClockSync {
    pub fn new() -> Self {
        Self {
            drift: Arc::new(AtomicI64::new(0)),
        }
    }

    pub fn get_synced_timestamp(&self) -> RoostooMs {
        let local_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as i64;
        let drift = self.drift.load(Ordering::Relaxed);
        let adjusted = local_ms + drift;
        RoostooMs(adjusted as u64)
    }

    pub fn drift(&self) -> i64 {
        self.drift.load(Ordering::Relaxed)
    }

    pub async fn start_background_sync(&self) -> Result<(), BotError> {
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(10))
            .tcp_nodelay(true)
            .pool_max_idle_per_host(1) // explicitly 1
            .build()
            .map_err(|e| BotError::Other(e.to_string()))?;
            
        let drift_clone = self.drift.clone();
        tokio::spawn(async move {
            let mut ticker = interval(Duration::from_secs(300));
            loop {
                ticker.tick().await;
                if let Err(e) = Self::sync_once(&client, &drift_clone).await {
                    match e {
                        BotError::ClockDriftCritical => {
                            eprintln!("FATAL: Background clock drift exceeded secure limits (30s). Terminating.");
                            std::process::exit(1);
                        }
                        _ => eprintln!("Background clock sync failed: {:?}", e)
                    }
                }
            }
        });

        Ok(())
    }

    pub async fn sync_once_direct(&self) -> Result<(), BotError> {
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(10))
            .tcp_nodelay(true)
            .pool_max_idle_per_host(1) // mapped specifically to explicitly defined limits
            .build()
            .map_err(|e| BotError::Other(e.to_string()))?;
            
        Self::sync_once(&client, &self.drift).await
    }

    async fn sync_once(client: &Client, drift_atomic: &Arc<AtomicI64>) -> Result<(), BotError> {
        let start_local = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as i64;

        let res: ServerTimeResponse = client
            .get("https://mock-api.roostoo.com/v3/serverTime")
            .send()
            .await?
            .json()
            .await
            .map_err(|e| BotError::Other(format!("Failed JSON ServerTime: {}", e)))?;

        let end_local = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as i64;

        let rtt = end_local - start_local;
        let server_timestamp = res.server_time as i64;
        let local_approx = start_local + (rtt / 2);
        
        let drift = server_timestamp - local_approx;
        
        if drift.abs() > 30000 {
            return Err(BotError::ClockDriftCritical);
        }
        
        drift_atomic.store(drift, Ordering::Relaxed);

        Ok(())
    }
}
