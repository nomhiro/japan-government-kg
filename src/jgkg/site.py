"""公開オントロジーを静的配信できる形に組み立てる。

**なぜ静的配信で足りるのか。** 語彙のURIはハッシュURI(`.../def/core#Agent`)である。
フラグメントはHTTPリクエストに含まれないので、サーバは `/def/core` を返せばよい。
つまり**トリプルストアを立てる前に、オントロジーだけを dereferenceable にできる。**
設計書の原則1「本体はオントロジーとKG、アプリは検証装置」に照らして、
ここが最初に公開すべきものである。

**解決すべきパスをハードコードしない。** 生成物の中で base 配下のIRIが主語として
現れるものを列挙し、それを正とする(`required_paths`)。ハードコードすると、
モジュールを増やしたときに黙って抜け落ちる — このプロジェクトで3回起きた型である。
"""
import shutil
from pathlib import Path

from rdflib import Graph, URIRef

from .config import get_settings


def _base() -> str:
    return get_settings().base_uri.rstrip("/")


def module_names(generated_dir: Path) -> list[str]:
    """配信すべきモジュール名(拡張子なしのエイリアス`/def/<module>`の対象)の一覧。

    **最終レビュー要修正2(裁定B40)。** `scripts/verify-site.py`は以前
    この一覧を`MODULES = ("core", "org", "all")`と手書きしていたため、
    `law`/`budget`モジュールの追加(Task 2/7)に追従できず、検査対象を
    3モジュールのまま固定してしまっていた(その2モジュールが公開先で
    1語も解決していない欠陥を、検査自体が見逃していた)。

    `build()`(下記)の「モジュール名だけのURI」を作るループと**同じ
    この関数を呼ぶ**ことで、ビルド側と検査側が同じ生成物から同じ計算を
    行い、二度と乖離できない形にする(手書きの一覧を複数箇所に置かない)。
    """
    return sorted(p.name.removesuffix(".owl.ttl") for p in generated_dir.glob("*.owl.ttl"))


def def_entry_count(generated_dir: Path) -> int:
    """`build()`が`made`へ`/def/`配下として追加する件数(sitemap掲載件数と一致する)。

    **最終レビュー⚠️B。** `scripts/verify-site.py`は以前
    `len(MODULES) * 3`(モジュールあたり3件という乗数)を手書きしていた。
    `MODULES`自体は要修正2で導出化したが、**この乗数だけが手書きのまま
    残っていた**——モジュールあたりの生成ファイル数(現在は`.owl.ttl`・
    `.shacl.ttl`の2件)や、エイリアスの有無が変われば黙って期待値が
    ずれる、同じ欠陥の型。

    `build()`が`made`に追加する2種類のループ(`*.ttl`の実ファイルコピー・
    `module_names()`のエイリアス)と**同じ2つの式**をここで数えるだけに
    し、`build()`を副作用込みで呼ばずに済ませる(`verify-site.py`は
    リモートのsiteを検査することもあり、検査のためにローカルへ書き込みを
    発生させたくない)。`tests/test_site.py`の一致テストで`build()`の
    実際の出力と結果が一致することを固定してある。

    `required_paths()`は**使わない**——これは生成OWLの主語IRIから
    導出した別の集合(SHACLファイルの主語は含まれず、`all`モジュールの
    エイリアス自体も主語に現れないため実測9件しかない。sitemapの実測は
    15件で一致しない)。「手で書かない」の対象は個々の値ではなく
    「`build()`が実際に作る個数」であり、それを最も正確に反映するのは
    `required_paths()`ではなくこの2つの式である。
    """
    return len(list(generated_dir.glob("*.ttl"))) + len(module_names(generated_dir))


def required_paths(generated_dir: Path) -> set[str]:
    """生成物が「このURLで解決されるべき」と主張しているパスを集める。

    生成OWL/SHACLの中で、ベースURI配下のIRIが**主語として**現れるものを対象にする。
    フラグメントは落とす(ハッシュURIはサーバまで届かない)。
    """
    base = _base()
    paths: set[str] = set()
    for f in sorted(generated_dir.glob("*.ttl")):
        g = Graph()
        g.parse(f, format="turtle")
        for s in set(g.subjects()):
            if isinstance(s, URIRef) and str(s).startswith(base):
                rest = str(s)[len(base) :].split("#")[0]
                if rest and rest != "/":
                    paths.add(rest)
    return paths


def build(generated_dir: Path, out_dir: Path) -> set[str]:
    """`out_dir` に配信用のファイルを作り、作ったパスの集合を返す。

    拡張子なしのエイリアス(`/def/core`)は**実ファイルとして作る。**
    プラットフォームの書き換え機能(`_redirects` の 200 rewrite 等)に依存しない方が
    移植性が高く、ここで検証もできる。数十KBの重複はその対価として妥当。
    """
    def_dir = out_dir / "def"
    if def_dir.exists():
        shutil.rmtree(def_dir)
    def_dir.mkdir(parents=True)

    made: set[str] = set()
    for f in sorted(generated_dir.glob("*.ttl")):
        shutil.copy2(f, def_dir / f.name)
        made.add(f"/def/{f.name}")

    # モジュール名だけのURI(`/def/core`)は skos:inScheme などで使われる。
    # 対応するOWLを同じ内容で置く。**`module_names()`と同じ計算を使う**
    # (要修正2/裁定B40。検査側〔verify-site.py〕もこの関数を呼ぶことで、
    # ビルド側と検査側のモジュール一覧が構造的に乖離できなくなる)。
    for module in module_names(generated_dir):
        owl = generated_dir / f"{module}.owl.ttl"
        shutil.copy2(owl, def_dir / module)
        made.add(f"/def/{module}")

    # sitemap を作る。**robots.txt がこれを名指ししているので、無いと
    # 「存在しないものへの参照」になる**(このプロジェクトで繰り返した
    # 「消費者のいない記録」の裏返し)。
    #
    # **`newline="\n"` を明示する。** 省略すると`write_text`はWindows上で
    # `\n`を`\r\n`に変換する(既定の`newline=None`の挙動)。CI(Linux)は常にLF
    # で作るため、Windows上でビルドしたときだけ配信済みの本番(LF)と
    # バイトが食い違う——`scripts/generate-schema.sh`に`MSYS_NO_PATHCONV=1`を
    # 足したのと同じ理由(設計書§11.1: どの環境で実行しても同じ生成物になる)。
    # 実測: Windows上でこの指定無しに作ると、本番と16バイト(改行16本分)食い違った。
    # **`/`(アプリ。D-5)と`/def/`(語彙の一覧ページ)は`made`に入れない。**
    # 前者はViteのビルド成果物(`sync_app()`が別に書く)、後者は手書きの
    # 静的ページ(`templates/def-index.html`。build-site.shが`def/index.html`へ
    # コピーする)であり、どちらも`schema/generated/`から導出した
    # turtleコンテンツではない——`made`をそのままsitemap行に流用すると
    # `_headers`のturtleブロック対象(下の`build_headers()`)にもこの2つが
    # 紛れ込んでしまう(HTMLにtext/turtleを名乗らせる誤り)。ここでは
    # ルート行と同じ扱いで、パスを直接書く(裁定B81)。
    base = _base()
    lines = [f"{base}/", f"{base}/def/"] + [f"{base}{p}" for p in sorted(made)]
    (out_dir / "sitemap.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    made.add("/sitemap.txt")

    return made


def sync_app(dist_dir: Path, out_dir: Path) -> set[str]:
    """フロントエンド(Viteビルド。裁定B81)の出力を`out_dir`直下へ同期する。

    **`/def/`配下とは完全に独立したツリーとして扱う。** Viteが書くのは
    `index.html`(アプリのシェル)と`assets/`(内容ハッシュ付きJS/CSS)だけ
    ——この2つに対象を絞って`out_dir`側の古い内容を`build()`の`def_dir`と
    同じ考え方(rmtreeしてから丸ごとコピー)で入れ替える。ハッシュ名が
    変わった古いチャンクを置き去りにしない(そうすると`site/assets/`が
    ビルドを重ねるたびに肥大化し、`verify-site.py`のバイト比較対象が
    「いま作ったもの」以外を含んでしまう)。

    `out_dir`の他の内容(`def/`・`robots.txt`・`sitemap.txt`・`_headers`・
    `def-index.html`)には一切触れない。
    """
    assets_out = out_dir / "assets"
    if assets_out.exists():
        shutil.rmtree(assets_out)
    index_out = out_dir / "index.html"
    if index_out.exists():
        index_out.unlink()

    made: set[str] = set()
    shutil.copy2(dist_dir / "index.html", index_out)
    made.add("/")

    dist_assets = dist_dir / "assets"
    if dist_assets.is_dir():
        shutil.copytree(dist_assets, assets_out)
        for p in sorted(assets_out.rglob("*")):
            if p.is_file():
                made.add(f"/assets/{p.relative_to(assets_out).as_posix()}")
    return made


def build_headers(made: set[str]) -> str:
    """Cloudflare Pagesの`_headers`の内容を、`build()`が実際に作ったパス

    (`made`)から生成する(最終レビュー要修正1。裁定B40)。

    **手書きのワイルドカード`/def/*`をやめた理由**: 以前の`_headers`は
    `/def/*`という1行のワイルドカードで、**マッチするパスが実在するかに
    関係なく** `Content-Type: text/turtle` を被せていた。Cloudflare Pages
    は存在しないパスに`index.html`を200で返す(実測 2026-08-23)ため、
    配信物が欠落しても「200 + text/turtle(本文はHTML)」になり——
    404より悪い。寛容なRDFパーサは0トリプル、厳格なパーサは構文エラーに
    なり、どちらも「語彙が存在しない」と見分けられない
    (`scripts/verify-site.py`の`_is_html_fallback`参照)。

    **実在する各パスに個別のブロックを与える**ことで、欠落したパスは
    このファイルに一致するブロックを持たない——Cloudflareの既定
    (`index.html`をtext/htmlで返す)に落ちるだけで、構造的にturtleを
    名乗れなくなる。陳腐化した配信が「200 + text/html」に劣化するのは
    まだ安全側の壊れ方である(RDFクライアントがHTMLをTurtleとして
    パースしようとしない)。

    **CORSを開ける理由**: LODはブラウザ内のクライアントからも参照される。
    公開語彙で`Access-Control-Allow-Origin`を絞る理由が無い
    (公共財として公開している)。
    """
    # **最終レビュー⚠️C。** 以前は`p != "/sitemap.txt"`(除外リスト。1要素)
    # だった。turtleを名乗るべきなのは`/def/`配下だけ、という構造を
    # 「何を除外するか」ではなく「何が対象か」で表現する
    # (`sitemap.txt`以外の非`/def/`パスが将来`made`に増えても、
    # 除外リストへの追記漏れで誤ってturtleブロックを持たない)。
    blocks: list[str] = []
    for path in sorted(p for p in made if p.startswith("/def/")):
        blocks.append(
            f"{path}\n"
            "  Content-Type: text/turtle; charset=utf-8\n"
            "  Access-Control-Allow-Origin: *\n"
            # 語彙は頻繁には変わらないが、変えたときに古いものを掴まれ続ける
            # のも困る。1時間 + 再検証で妥協する。
            "  Cache-Control: public, max-age=3600, must-revalidate"
        )

    # **アプリ(裁定B81)の資産用ワイルドカード。**
    #
    # **かつてここは `max-age=31536000, immutable`(1年)だった。**
    # そのときのコメントは「欠落時はCloudflareの既定`index.html`に
    # フォールバックし、その本文にこのCache-Controlが付くだけ——値が
    # 『1年キャッシュしてよい』であること自体は害にならない」と論証していた。
    # **その論証は誤りだった(裁定B85。2026-09-02に実測で否定された)。**
    #
    # 実際に起きたこと: 配備が伝播する前に、あるPoPが
    # `/assets/index-BZcjP9V0.js` を要求した。Cloudflareは**200 + HTML**
    # (欠落パスへのフォールバック)を返し、**このパスにマッチする
    # `Cache-Control: max-age=31536000, immutable` を付けて1年間保存した。**
    # 以後そのPoPは、実物が配備済みでも古いHTMLを返し続けた
    # (CI実行2回・20分離れて同一のsha256を観測。別PoPからは正しいJSが返る)。
    # **一過性の伝播遅れが、恒久的な破損に固定された。**
    # そのPoPを使う実利用者にはアプリが永久に読み込めない
    # ——ブラウザ側も同じヘッダで1年保持するため、再訪でも直らない。
    #
    # **内容ハッシュ付きファイル名は、正しさをTTLに依存させない**
    # (内容が変われば別名になる)。だから1年という長さが買っていたのは
    # 再検証1往復の節約だけであり、その代償が上記だった。**割に合わない。**
    # `/def/*` と同じ「1時間 + 再検証」に揃える——ETag付きの再検証は
    # 304を返すだけで安く、この規模の公開サイトでは無視できる。
    #
    # **重要(2026-09-05実測。裁定B85の訂正)**: ここに書いた値が
    # **利用者に届くとは限らない。** 本番で測ると:
    #   /def/core        宣言3600 → 配信3600(cf-cache-status: DYNAMIC)
    #   /assets/*.js     宣言3600 → **配信14400**(cf-cache-status: HIT)
    # **エッジにキャッシュされる応答では Cloudflare が Cache-Control を
    # 自分の値に置き換える**(14400の出どころはゾーン設定と推測。未確定)。
    # `_headers`自体は届いている——`/*`が宣言するnosniff/Referrer-Policyは
    # 全応答に付く。**Cache-Controlだけがこの経路で置き換わる。**
    #
    # したがって**この値を短くしたこと自体は、実際の配信を変えていない
    # 可能性が高い。** それでも宣言として正しいので残す
    # (内容ハッシュ付きファイル名は正しさをTTLに依存させない)。
    # **「3600が利用者に届く」と読まないこと。**
    #
    # この行は`made`の中身に関わらず常に出す
    # ——アプリは`/def/`と並ぶ、このサイトの恒久的な構成要素だから。
    blocks.append(
        "/assets/*\n"
        "  Cache-Control: public, max-age=3600, must-revalidate"
    )
    blocks.append(
        "/*\n"
        "  X-Content-Type-Options: nosniff\n"
        "  Referrer-Policy: strict-origin-when-cross-origin"
    )
    return "\n\n".join(blocks) + "\n"


def write_headers(made: set[str], out_dir: Path) -> Path:
    """`build_headers()`の内容を`out_dir/_headers`に書く。書いたパスを返す。

    `newline="\\n"`を明示する理由は`build()`の`sitemap.txt`と同じ
    (Windows上での既定`newline=None`はLFをCRLFに変換する)。
    """
    path = out_dir / "_headers"
    path.write_text(build_headers(made), encoding="utf-8", newline="\n")
    return path


def missing_paths(generated_dir: Path, out_dir: Path) -> set[str]:
    """生成物が要求しているのに配信物に無いパスを返す。空集合なら整合している。"""
    required = required_paths(generated_dir)
    return {p for p in required if not (out_dir / p.lstrip("/")).is_file()}


# --- A-2: ビルド成果物のCI検査(`scripts/check-site-build.py`)向け。 -------
#
# 以下の3関数は「導出」ではなく**観測**である。`module_names()`や
# `def_entry_count()`のように`build()`の内部計算と同じ式を再利用するの
# ではなく、`out_dir`に実際に書かれたファイル・`_headers`・`sitemap.txt`
# を、それぞれ独立にファイルシステム/テキストから読み直す。
#
# 理由: `check-site-build.py`がしたいのは「`_headers`とsitemap.txtは、
# build()が実際に作った実体と一致しているか」の検査であり、その一致を
# `build()`が最初に何を`made`へ入れたかの式で測ると、`build()`自身の
# バグ(例: `made`には入れたが実ファイルは書き損じた)を検査が原理的に
# 見逃す(循環検証になる)。そこで基準点を`out_dir/def/`の**実際の
# ディレクトリ一覧**(`built_def_paths`)に固定し、`_headers`と
# `sitemap.txt`という**別々の2つのテキスト**をそれぞれ独立にこの基準点
# と突き合わせる。


def built_def_paths(out_dir: Path) -> set[str]:
    """`out_dir/def/`に実在するturtleコンテンツのファイルから`/def/`パスの集合を得る(観測)。

    **`index.html`(語彙の一覧ページ。裁定B81)は除く。** この関数の
    結果は`_headers`のturtleブロック対象・sitemapの`/def/`集合との
    一致検査(下記)に使われる——一覧ページはTurtleではないので、
    ここに混ぜると「HTMLにtext/turtleを名乗らせるべき」という誤った
    要求を検査自身が生んでしまう。一覧ページ自身の存在・内容は
    `site_verify`(構造検査。裁定B65)が別に見る。
    """
    def_dir = out_dir / "def"
    if not def_dir.is_dir():
        return set()
    return {
        f"/def/{p.name}" for p in def_dir.iterdir() if p.is_file() and p.name != "index.html"
    }


def headers_declared_paths(out_dir: Path) -> set[str]:
    """`out_dir/_headers`の実テキストから、turtleを名乗る`/def/`パスの集合を読む。

    `build_headers()`の出力形式(空行区切りのブロック、各ブロック先頭行が
    パス)をそのまま解釈するだけで、`build_headers()`を呼び直しはしない。
    """
    path = out_dir / "_headers"
    if not path.is_file():
        return set()
    declared: set[str] = set()
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        lines = block.splitlines()
        if lines and lines[0].strip().startswith("/def/"):
            declared.add(lines[0].strip())
    return declared


def sitemap_declared_paths(out_dir: Path) -> set[str]:
    """`out_dir/sitemap.txt`の実テキストから、`/def/`配下のturtleコンテンツのURLの集合を読む。

    各行からbase URIの接頭辞を剥がすだけで、`build()`のsitemap生成ロジック
    (`made`の集計)は呼び直しはしない。ルート行(`{base}/`)は対象外。

    **`{base}/def/`(語彙の一覧ページ自身。裁定B81)も対象外。** `build()`は
    これをルート行と同じ扱いで`made`と無関係に書く(`built_def_paths()`が
    `index.html`を除く理由と同じ——一覧ページはTurtleではない)。ここに
    混ぜると`built_def_paths()`との一致検査が常に「sitemap側だけ1件多い」
    という偽の不一致を報告する。
    """
    path = out_dir / "sitemap.txt"
    if not path.is_file():
        return set()
    base = _base()
    declared: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith(base):
            continue
        rest = line[len(base) :]
        if rest.startswith("/def/") and rest != "/def/":
            declared.add(rest)
    return declared
