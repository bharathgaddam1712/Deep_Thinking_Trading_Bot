use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::RwLock;

pub struct SymbolState {
    pub price_precision: u32,
    pub amount_precision: u32,
    pub mini_order: f64,
}

pub struct GlobalState {
    pub symbols: RwLock<HashMap<String, SymbolState>>,
    // f64 bitcasted to u64 for performant, lock-free atomic representation
    initial_usd_balance: AtomicU64,
    current_usd_balance: AtomicU64,
    pub drawdown_halt: AtomicBool,
}

impl GlobalState {
    pub fn new() -> Self {
        Self {
            symbols: RwLock::new(HashMap::new()),
            initial_usd_balance: AtomicU64::new(0f64.to_bits()),
            current_usd_balance: AtomicU64::new(0f64.to_bits()),
            drawdown_halt: AtomicBool::new(false),
        }
    }

    #[inline(always)]
    pub fn set_balance(&self, balance: f64) {
        let bits = balance.to_bits();
        // If initial balance is exactly 0.0, this is the first load
        if self.get_initial_balance() == 0.0 {
            self.initial_usd_balance.store(bits, Ordering::Relaxed);
        }
        self.current_usd_balance.store(bits, Ordering::Relaxed);
        self.check_drawdown();
    }

    #[inline(always)]
    pub fn get_initial_balance(&self) -> f64 {
        f64::from_bits(self.initial_usd_balance.load(Ordering::Relaxed))
    }

    #[inline(always)]
    pub fn get_current_balance(&self) -> f64 {
        f64::from_bits(self.current_usd_balance.load(Ordering::Relaxed))
    }

    #[inline(always)]
    pub fn check_drawdown(&self) {
        let current = self.get_current_balance();
        let initial = self.get_initial_balance();
        if initial > 0.0 {
            let drawdown = (initial - current) / initial;
            // 5% Drawdown Limit Circuit Breaker
            if drawdown > 0.05 {
                self.drawdown_halt.store(true, Ordering::Relaxed);
            }
        }
    }
}
