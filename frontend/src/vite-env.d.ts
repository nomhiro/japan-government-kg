/// <reference types="vite/client" />

interface ImportMetaEnv {
  // APIの本番URL(ビルド時の設定値。D-6b未決のため既定はローカル。
  // src/api/client.tsのAPI_BASE参照)。
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
