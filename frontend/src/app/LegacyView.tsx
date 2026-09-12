import { useEffect, useRef, type JSX } from "react";

// 旧ビュー(frontend/src/views/*.ts。innerHTML を書く関数)を React ツリーに
// 載せるための橋。**Phase 0〜3 の移行期間だけ存在し、旧ビューが全部 React に
// 置き換わったら削除する**(仕様 §4 移行方式 Strangler)。
//
// 契約:
// - mount は**マウント時に1回だけ**呼ぶ。props.mount の参照が変わっても呼び直さない
//   (シェルのテーマ切替などで親が再描画されるたびに旧ビューが fetch し直すのを防ぐ)。
//   ルートが変わったら描き直したい親は `key` を変える(App.tsx は routeToHash(route) を key にする)。
// - アンマウント時に controller.destroy() を呼ぶ(entity 画面の Sigma/WebGL を確実に破棄する。
//   旧 main.ts:14-20 と同じ責務)。controller を返さない旧ビューも許す。
// - 開発時の <StrictMode> は effect を mount→cleanup→mount と二重実行する。旧ビューは
//   その結果 2回描かれ、entity 画面は fetch も2回走る。**本番ビルドでは起きない**。
//   StrictMode を外して隠すより、新しい React 部品の cleanup 漏れを開発中に見える方を採る。

export interface LegacyController {
  destroy(): void;
}

export type LegacyMount = (el: HTMLElement) => LegacyController | void;

export function LegacyView({ mount }: { mount: LegacyMount }): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  const mountRef = useRef(mount);
  mountRef.current = mount;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const controller = mountRef.current(el);
    return () => {
      controller?.destroy();
      el.replaceChildren();
    };
    // 依存配列を空にするのは意図(上の契約)。再マウントは親の key で行う。
  }, []);

  return <div ref={ref} className="jgkg-legacy" />;
}
