fn main() {
    std::env::set_var("PROTOC", protoc_bin_vendored::protoc_bin_path().unwrap());
    prost_build::compile_protos(&["proto/trading.proto"], &["proto/"]).unwrap();
}
