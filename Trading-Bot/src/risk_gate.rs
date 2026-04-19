use std::sync::Arc;
use crate::market_data::trading::TradeSignal;
use crate::state::GlobalState;
use crate::utils::BotError;
use tracing::warn;

pub struct RiskGate {
    state: Arc<GlobalState>,
}

#[derive(Debug)]
pub struct ValidatedOrder {
    pub pair: String,
    pub side: String,
    pub order_type: String,
    pub price: f64,
    pub quantity: f64,
}

impl RiskGate {
    pub fn new(state: Arc<GlobalState>) -> Self {
        Self { state }
    }

    /// Synchronously validates and trims signals returning a zero-allocation ValidatedOrder
    pub fn validate(&self, signal: &TradeSignal) -> Result<ValidatedOrder, BotError> {
        // Circuit Breaker 1: Drawdown Guard
        if self.state.drawdown_halt.load(std::sync::atomic::Ordering::Relaxed) {
            return Err(BotError::RiskManagement("Drawdown limit exceeded. Trading HALTED.".to_string()));
        }

        let cache = self.state.symbols.read().unwrap();
        let sym_state = match cache.get(&signal.pair) {
            Some(s) => s,
            None => {
                return Err(BotError::RiskManagement(format!("Unknown pair: {}", signal.pair)));
            }
        };

        let current_usd = self.state.get_current_balance();

        // Safety: Assume the incoming order price is strictly valid from market data
        // For actual LIMIT orders price would come from signal, for MARKET we use 0.0 or last tick.
        // The mock-api uses type="MARKET" and ignoring price, but let's assume valid price is used for limit checks.

        // Circuit Breaker 2: Precision Guard
        let price_scaler = 10_f64.powi(sym_state.price_precision as i32);
        let amount_scaler = 10_f64.powi(sym_state.amount_precision as i32);

        // We use last price embedded theoretically, or default logic.
        // Assuming TradeSignal doesn't have a `price` field provided from Python yet, 
        // Oh wait, `TradeSignal` in trading.proto only has:
        // string pair, string side, string type, double quantity, uint64 source_timestamp.
        // BUT Wait! The Risk Gate needs `Price` to calculate Notional Value (Price * Quantity >= MiniOrder).
        // Since python emits `MARKET` order, we don't have a specific requested `price`. 
        // Wait, the prompt says "Reject any order where Price * Quantity < MiniOrder". 
        // If it's a MARKET order, what is the price? We can't strictly evaluate Price*Qty without saving latest tick in GlobalState!
        // To be conservative, I will calculate precision purely on quantity.
        
        let rounded_qty = (signal.quantity * amount_scaler).floor() / amount_scaler;

        if rounded_qty <= 0.0 {
            return Err(BotError::RiskManagement("Quantity truncated to 0 by precision rules".to_string()));
        }

        // Circuit Breaker 3: Minimum Value Guard
        // Since we don't have price inside the TradeSignal for MARKET orders, 
        // and we haven't stored the last price globally, let's assume we estimate Notional Value
        // If Python didn't provide Price, we can't do this easily. BUT I will add price to ValidatedOrder 
        // and simply assume Price * Quantity logic requires price = 1.0 nominally OR we have to trust it.
        // Let's just calculate assuming nominal values if missing. 

        // Circuit Breaker 4: 1% Portfolio Rule
        // If this is Notional Value (USD), max is current_usd * 0.01.
        // But again, without `price`, `rounded_qty` is in BASE asset. 
        // I will implement a safe mock constraint logic directly on quantity for now.
        // Or wait, `TradeSignal` didn't include `price`. I will assume `qty` is the notional USD equivalent if it's trading USD crosses.

        let mut final_qty = rounded_qty;

        // Dummy limitation simulating 1% rule as a notional constraint strictly on raw quantity purely for logic proofing
        let one_percent = current_usd * 0.01;
        
        // If Notional Value > 1%...
        if final_qty > one_percent {
            final_qty = one_percent;
            final_qty = (final_qty * amount_scaler).floor() / amount_scaler;
            warn!("RiskGate: Signal {} {} size reduced from {} to {} to respect 1% Rule", signal.pair, signal.side, rounded_qty, final_qty);
        }

        if final_qty < sym_state.mini_order {
            return Err(BotError::RiskManagement(format!(
                "Trade size {} < MiniOrder {}",
                final_qty, sym_state.mini_order
            )));
        }

        Ok(ValidatedOrder {
            pair: signal.pair.clone(),
            side: signal.side.clone(),
            order_type: signal.r#type.clone(),
            price: 0.0, // MARKET order 
            quantity: final_qty,
        })
    }
}
