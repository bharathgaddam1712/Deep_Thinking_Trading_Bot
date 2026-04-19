use crate::utils::Secret;
use ring::hmac;
use bytes::BytesMut;
use smallvec::SmallVec;
use std::borrow::Cow;
use reqwest::header::{HeaderMap, HeaderValue};

pub struct SignedRequest {
    pub headers: HeaderMap,
    pub query_string: String,
}

pub struct OrderedParams<'a> {
    params: SmallVec<[(&'a str, Cow<'a, str>); 16]>,
}

impl<'a> OrderedParams<'a> {
    pub fn new() -> Self {
        Self {
            params: SmallVec::new(),
        }
    }

    pub fn insert(&mut self, key: &'a str, value: impl Into<Cow<'a, str>>) {
        self.params.push((key, value.into()));
    }

    pub fn build_query_string(&mut self, buffer: &mut BytesMut) {
        // In-place lexicographical sort
        self.params.sort_unstable_by(|a, b| a.0.cmp(&b.0));
        
        let mut first = true;
        for (k, v) in &self.params {
            if !first {
                buffer.extend_from_slice(b"&");
            }
            first = false;
            buffer.extend_from_slice(k.as_bytes());
            buffer.extend_from_slice(b"=");
            buffer.extend_from_slice(v.as_bytes());
        }
    }
}

pub struct Signer {
    key: hmac::Key,
    api_key: Secret<String>,
}

impl Signer {
    pub fn new(secret_key: Secret<String>, api_key: Secret<String>) -> Self {
        let key = hmac::Key::new(hmac::HMAC_SHA256, secret_key.inner().as_bytes());
        Self { key, api_key }
    }

    pub fn prepare_request(&self, query_string_buffer: &[u8]) -> SignedRequest {
        let signature = hmac::sign(&self.key, query_string_buffer);
        let signature_hex = hex::encode(signature.as_ref());

        let mut headers = HeaderMap::new();
        if let Ok(val) = HeaderValue::from_str(self.api_key.inner()) {
            headers.insert("RST-API-KEY", val);
        }
        if let Ok(val) = HeaderValue::from_str(&signature_hex) {
            headers.insert("MSG-SIGNATURE", val);
        }

        SignedRequest {
            headers,
            query_string: std::str::from_utf8(query_string_buffer).unwrap_or("").to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_generate_signature() {
        let secret = Secret::new("S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep".to_string());
        let api = Secret::new("USEAPIKEYASMYID".to_string());
        let signer = Signer::new(secret, api);
        
        let mut params = OrderedParams::new();
        params.insert("pair", "BNB/USD");
        params.insert("quantity", "2000");
        params.insert("side", "BUY");
        params.insert("timestamp", "1580774512000");
        params.insert("type", "MARKET");

        let mut buffer = BytesMut::with_capacity(256);
        params.build_query_string(&mut buffer);
        
        let req = signer.prepare_request(&buffer);
        
        let expected_query_string = "pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET";
        assert_eq!(req.query_string, expected_query_string);

        assert_eq!(req.headers.get("MSG-SIGNATURE").unwrap().to_str().unwrap(), "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff");
        assert_eq!(req.headers.get("RST-API-KEY").unwrap().to_str().unwrap(), "USEAPIKEYASMYID");
    }
}
