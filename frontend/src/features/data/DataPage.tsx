// データとAPI画面(#/data)。新規(旧実装には相当する画面が無く、`/def/`への
// 生リンクだけだった)。開発者と、データの出自を確かめたい人のための画面。
import { useMemo, type JSX } from "react";
import { API_BASE, apiUnavailableReason, fetchOverview } from "../../api/client";
import { useApiQuery } from "../../api/useApiQuery";
import { Band, ErrorBox, Loading, Section } from "../../components/ui";
import { typeLabel } from "../../labels";
import { foldFreshness } from "../../lib/freshness";
import { localNameFromIri } from "../../lib/overview-format";
import "./data.css";

const RELEASES_URL = "https://github.com/nomhiro/japan-government-kg/releases";
const PDL_URL = "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0";

const ONTOLOGY_MODULES: readonly { path: string; label: string }[] = [
  { path: "/def/", label: "語彙の一覧" },
  { path: "/def/core", label: "core(6軸の基礎語彙)" },
  { path: "/def/law", label: "law(法令)" },
  { path: "/def/org", label: "org(府省・法人などの組織)" },
  { path: "/def/budget", label: "budget(予算事業・支出)" },
  { path: "/def/all", label: "all(全モジュールの結合)" },
];

const API_ENDPOINTS: readonly { method: string; path: string; description: string }[] = [
  { method: "GET", path: "/overview", description: "トップページ第1層。府省別予算・型ごとの件数など" },
  { method: "GET", path: "/search", description: "名前の部分一致検索(府省・国の機関・法令・予算事業など)" },
  { method: "GET", path: "/entity/{id}", description: "1エンティティの属性・関係の一覧" },
  { method: "GET", path: "/neighborhood/{id}", description: "1エンティティ周辺の近傍サブグラフ" },
  { method: "GET", path: "/path", description: "2エンティティ間の経路探索" },
  { method: "POST", path: "/chat", description: "道具を使ってナレッジグラフを調べ、出典付きで答える" },
];

const PRIMARY_SOURCES: readonly { label: string; url: string }[] = [
  { label: "e-Gov法令検索", url: "https://laws.e-gov.go.jp/" },
  { label: "法人番号公表サイト(国税庁)", url: "https://www.houjin-bangou.nta.go.jp/" },
  { label: "行政事業レビュー見える化サイト(RS)", url: "https://rssystem.go.jp/" },
];

export function DataPage(): JSX.Element {
  const unavailable = apiUnavailableReason();
  const state = useApiQuery(unavailable ? null : "overview", fetchOverview);

  // 鮮度(CQ10。裁定B111)。**任意として読む** ——この項目を返さない版の
  // APIが相手のこともある(裁定B103追記7)。無ければ節を出さない。
  const freshnessRows = useMemo(() => {
    if (state.status !== "ready" || state.data === undefined) return [];
    // 同じソースが複数の名前付きグラフに分かれていると同じ行が並ぶ
    // (本番実測。`lib/freshness.ts` 参照)。表示では畳む。
    return foldFreshness(state.data.release_freshness ?? []);
  }, [state]);

  const typeRows = useMemo(() => {
    if (state.status !== "ready" || state.data === undefined) return [];
    return [...state.data.type_counts]
      .map((tc) => ({ localName: localNameFromIri(tc.type), count: tc.instance_count }))
      .sort((a, b) => b.count - a.count);
  }, [state]);

  return (
    <Band full>
      <Section title="データとAPI" eyebrow="開発者・データの出自を確かめたい方向け">
        <div className="jg-stack jg-stack--7">
          <div className="jg-stack jg-stack--3">
            <h3 className="jg-h3">このKGは何か</h3>
            <p>
              日本政府ナレッジグラフは、e-Gov法令検索・国税庁法人番号公表サイト・行政事業レビュー見える化サイト
              (RS)など複数の政府公開データを、法令・府省・予算事業・支出・法人などのエンティティとして
              結びつけ直したRDFのナレッジグラフです。非公式の第三者による構造化データであり、政府自身が
              提供するものではありません。
            </p>
          </div>

          {freshnessRows.length > 0 ? (
            <div className="jg-stack jg-stack--3">
              <h3 className="jg-h3">データの時点</h3>
              <p className="jg-sm jg-ink2">
                このKGが各ソースについていつ時点のデータを含むかです。
                <strong>「取得日」と「記録日」は意味が違います</strong>
                ——APIから取得した日が分かるソースと、全件ファイルのように
                「記録した日」しか分からないソースがあるためです。
              </p>
              <table className="jg-table">
                <thead>
                  <tr>
                    <th scope="col">ソース</th>
                    <th scope="col">いつ時点か</th>
                    <th scope="col">日付の種類</th>
                  </tr>
                </thead>
                <tbody>
                  {freshnessRows.map((row) => (
                    <tr key={`${row.sourceName}|${row.asOfDate}|${row.dateKind}`}>
                      <td>{row.sourceName}</td>
                      <td className="jg-num">{row.asOfDate}</td>
                      <td>{row.dateKind}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="jg-xs jg-muted">
                出所: {state.status === "ready" && state.data
                  ? state.data.sources.release_freshness
                  : ""}
              </p>
            </div>
          ) : null}

          <div className="jg-stack jg-stack--3">
            <h3 className="jg-h3">ライセンス</h3>
            <p>
              元データ(各府省庁・機関が公開した内容そのもの)は、それぞれの出典元が指定する
              <a href={PDL_URL} target="_blank" rel="noopener noreferrer">
                公共データ利用規約(第1.0版)(PDL1.0)
              </a>
              に従います。PDL1.0は利用にあたって出典の表示に加え、
              <strong>編集・加工を行ったこと及びその主体の記載</strong>
              を求めています。本サイトは元データをRDFへの変換・エンティティの結合・オントロジーへの
              マッピングという形で編集・加工しており、その主体は本サイトの運営者(GitHub:
              <a href="https://github.com/nomhiro/japan-government-kg" target="_blank" rel="noopener noreferrer">
                nomhiro/japan-government-kg
              </a>
              )です。
            </p>
            <p className="jg-sm jg-muted">
              一方、データの構造化・RDF化・オントロジー設計そのもの(この成果物)はCC BY 4.0で提供します。
              元データを私たち自身が再ライセンスするものではありません——各出典元の出典表示・編集加工の
              記載義務は、それぞれのPDL1.0に従います。詳しい出典ごとの一覧はGitHub Releasesのリリースノートに
              全量を記載しています。
            </p>
          </div>

          <div className="jg-stack jg-stack--3">
            <h3 className="jg-h3">KG本体のダウンロード</h3>
            <p>
              <a href={RELEASES_URL} target="_blank" rel="noopener noreferrer">
                GitHub Releases
              </a>
              から配布しています。各リリースには3つの資産があります: N-Quads本体(<code>kg.nq.gz</code>)・
              Jena TDB2の索引済みデータ(<code>tdb2.tar.gz</code>)・トリプル数やソースの取得日・
              各資産のsha256を記録した<code>manifest.json</code>。出典・ライセンス・sha256はリリースノートに
              全量を載せています。
            </p>
          </div>

          <div className="jg-stack jg-stack--3">
            <h3 className="jg-h3">語彙(オントロジー)</h3>
            <p>
              語彙は<code>/def/</code>配下の恒久的なLOD識別子として公開しています。<code>text/turtle</code>
              で解決します。
            </p>
            <ul className="jg-data-links">
              {ONTOLOGY_MODULES.map((m) => (
                <li key={m.path}>
                  <a href={m.path}>{m.path}</a> — {m.label}
                </li>
              ))}
            </ul>
          </div>

          <div className="jg-stack jg-stack--3">
            <h3 className="jg-h3">APIの使い方</h3>
            <p>
              ベースURL: <code>{API_BASE}</code>
            </p>
            <div className="jg-scroll-x">
              <table className="jg-table">
                <thead>
                  <tr>
                    <th>メソッド</th>
                    <th>パス</th>
                    <th>説明</th>
                  </tr>
                </thead>
                <tbody>
                  {API_ENDPOINTS.map((ep) => (
                    <tr key={ep.path}>
                      <td>
                        <code>{ep.method}</code>
                      </td>
                      <td>
                        <code>{ep.path}</code>
                      </td>
                      <td>{ep.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <pre className="jg-code">
              <code>{`curl "${API_BASE}/search?q=${encodeURIComponent("年金")}&limit=20"`}</code>
            </pre>
          </div>

          <div className="jg-stack jg-stack--3">
            <h3 className="jg-h3">一次資料</h3>
            <p className="jg-sm jg-muted">
              このKGが結びつけている、政府公開データそのものの取得元です。個々のエンティティの一次資料
              (取得日・ライセンス付き)は、各エンティティのページに出しています。
            </p>
            <ul className="jg-data-links">
              {PRIMARY_SOURCES.map((s) => (
                <li key={s.url}>
                  <a href={s.url} target="_blank" rel="noopener noreferrer">
                    {s.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          <div className="jg-stack jg-stack--3">
            <h3 className="jg-h3">型ごとの件数</h3>
            {unavailable ? (
              <ErrorBox>データ取得は準備中です。{unavailable}</ErrorBox>
            ) : state.status === "error" ? (
              <ErrorBox>件数をいま出せません。</ErrorBox>
            ) : state.status !== "ready" || state.data === undefined ? (
              <Loading label="読み込み中" />
            ) : (
              <>
                <div className="jg-scroll-x">
                  <table className="jg-table">
                    <thead>
                      <tr>
                        <th>型</th>
                        <th className="jg-table__num">件数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {typeRows.map((row) => (
                        <tr key={row.localName}>
                          <td>{typeLabel(row.localName)}</td>
                          <td className="jg-table__num jg-num">{row.count.toLocaleString("ja-JP")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="jg-xs jg-muted">
                  この画面の数字を集計した時刻: {state.data.computed_at}
                  (APIプロセスが起動時に集計した時刻です。KGそのものの更新時刻ではありません)
                </p>
              </>
            )}
          </div>
        </div>
      </Section>
    </Band>
  );
}
