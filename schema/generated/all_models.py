from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "1.11.0"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )





class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'jgkgall',
     'default_range': 'string',
     'description': 'SHACL検証のために全モジュールを1つに束ねるだけのスキーマ。ここから生成した all.shacl.ttl '
                    'を検証の唯一の入力にする。モジュール別に生成すると、import された '
                    '上位モジュールのシェイプが各ファイルに重複して現れ、閉じたシェイプが同一クラスに 複数適用されて偽の違反になるため。 '
                    '新しいドメインモジュールを追加したら、必ずここの imports にも追加する。 '
                    'このオントロジーは日本国政府が公開するデータを第三者が構造化したものであり、日本国政府による公式なデータセットではない。',
     'id': 'https://jgkg.norr-tech.com/def/all',
     'imports': ['linkml:types', 'core', 'org', 'law', 'budget'],
     'license': 'https://creativecommons.org/licenses/by/4.0/',
     'name': 'jgkg-all',
     'prefixes': {'jgkgall': {'prefix_prefix': 'jgkgall',
                              'prefix_reference': 'https://jgkg.norr-tech.com/def/all#'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'schema/all.yaml',
     'title': '日本政府ナレッジグラフ 全モジュール統合(検証用)'} )

class UnresolvedReasonEnum(str, Enum):
    """
    参照が未解決である理由の分類
    """
    NO_CANDIDATE = "NO_CANDIDATE"
    """
    候補が見つからず、政府機関の形(省/府/庁/院/委員会で終わる、又は 「人事院」「閣」そのもの)にも当たらない。抽出そのものを疑うべき警報
    """
    AMBIGUOUS = "AMBIGUOUS"
    """
    候補が複数あり一意に決められなかった
    """
    OBSOLETE_ORGANIZATION = "OBSOLETE_ORGANIZATION"
    """
    政府機関の形(省/府/庁/院/委員会で終わる、又は「人事院」「閣」 そのもの)をしているが、現存府省の参照表にも `old-ministries.csv` (OLD_MINISTRY が一致を見る、2001年の中央省庁再編で廃止された名称の 一覧)にも一致しない — **判定はOLD_MINISTRYを先に見て、そこに当たらなかったものの残り**。 2001年より前に廃止された省庁名や、参照表にまだ収録されていない 現存機関などが該当し得る(裁定B7。列挙ではなく形から導出するため、 参照表の完全性次第で現存機関がここに一時的に入り得る)
    """
    OLD_MINISTRY = "OLD_MINISTRY"
    """
    参照表に一意に一致すれば resolved、複数一致すれば AMBIGUOUS が 先に成立する。**いずれでもない場合に限り** `old-ministries.csv`(2001年の中央省庁再編で廃止された名称の一覧。 高信頼・出典あり)との一致を見て、一致すればこの値になる。 **この一覧に一致しない場合は OBSOLETE_ORGANIZATION 側で判定する** (裁定B7でこの enum の意味をこの一覧との一致に狭めた — それ以前に廃止された省庁は `OBSOLETE_ORGANIZATION` に分類する)
    """



class Entity(ConfiguredBaseModel):
    """
    本KGが扱うすべての事物の基底
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True,
         'children_are_mutually_disjoint': True,
         'from_schema': 'https://jgkg.norr-tech.com/def/core'})

    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class Agent(Entity):
    """
    「誰が」の軸。行為の主体。組織と人の上位
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'exact_mappings': ['prov:Agent'],
         'from_schema': 'https://jgkg.norr-tech.com/def/core'})

    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class Work(Entity):
    """
    「何を」の軸。法令・政策・事業・文書・司法判断の上位
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'close_mappings': ['schema:CreativeWork'],
         'from_schema': 'https://jgkg.norr-tech.com/def/core'})

    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class Place(Entity):
    """
    「どこで」の軸。行政区域・住所・地物の上位
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'close_mappings': ['schema:Place'],
         'from_schema': 'https://jgkg.norr-tech.com/def/core'})

    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class Event(Entity):
    """
    「いつ」の軸。時点を持つ出来事。関係を実体化するための中心クラス。 「AがBに影響した」を直接のエッジにせず、原則としてこのクラスを介す
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'close_mappings': ['prov:Activity'],
         'from_schema': 'https://jgkg.norr-tech.com/def/core'})

    occurred_on: Optional[date] = Field(default=None, description="""この出来事が起きた日""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    involves_agent: Optional[str] = Field(default=None, description="""この出来事に関与した主体""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class MonetaryItem(Entity):
    """
    「いくらで」の軸。予算科目・支出の上位
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/core'})

    amount_jpy: Optional[int] = Field(default=None, description="""金額(円)""", json_schema_extra = { "linkml_meta": {'domain_of': ['MonetaryItem']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class Concept(Entity):
    """
    「何について」の軸。主題・指標・制度手続きの上位
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'exact_mappings': ['skos:Concept'],
         'from_schema': 'https://jgkg.norr-tech.com/def/core'})

    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class UnresolvedReference(Entity):
    """
    正準IDに解決できなかった参照。設計書§8.2により、未解決を沈黙させず KGに残して計測できるようにするためのクラス
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/core'})

    unresolved_text: Optional[str] = Field(default=None, description="""正準IDに解決できなかった元の参照文字列""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedReference']} })
    unresolved_reason: Optional[UnresolvedReasonEnum] = Field(default=None, description="""解決できなかった理由""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedReference']} })
    unresolved_key: Optional[str] = Field(default=None, description="""解決できなかった参照の、ソース側のキー(府省コード等)。ドメイン固有の プロパティを UnresolvedReference に足すと閉じたSHACLシェイプに違反するため、 汎用のキーとしてここで受ける""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedReference']} })
    unresolvedFor: Optional[str] = Field(default=None, description="""この未解決参照が生じた主体(参照元のエンティティ)。CQ9等が未解決ノード からその主体へグラフパターンで辿れるようにするための辺(URIの再構成を 要しない。裁定B8)。方向はUnresolvedReference→主体(逆向きにすると、 未解決を持ち得る全クラスがこのプロパティを宣言する必要が生じ、閉じた シェイプが増殖する。unresolved_keyを汎用スロットとしてUnresolvedReference 側に置いたのと同じ設計)。**必須にしない** — 主体を特定できない未解決 (例: emit_ministriesの未解決府省。参照表の1行がどの組織にも対応しない だけで、特定の「この記述の主体」が無い)を壊さないため""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedReference']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class Organization(Agent):
    """
    法人番号を持つ組織
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'close_mappings': ['schema:Organization'],
         'from_schema': 'https://jgkg.norr-tech.com/def/org'})

    houjinBangou: Optional[str] = Field(default=None, description="""国税庁が付与する13桁の法人番号。組織の正準ID。 required にしないのは、出典管理のためグラフをソース別に分けており、 1つのエンティティの記述が複数グラフに分かれるため。SHACL検証はグラフ単位 (グラフが置換の単位)なので、グラフを跨いだ必須制約は原理的に検証できない。 「全Organizationが法人番号を持つ」ことはCQのSPARQLテストで担保する""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    organizationKindCode: Optional[str] = Field(default=None, description="""法人番号公表サイトの法人種別コード""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    prefectureName: Optional[str] = Field(default=None, description="""所在地の都道府県名""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    cityName: Optional[str] = Field(default=None, description="""所在地の市区町村名""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })

    @field_validator('houjinBangou')
    def pattern_houjinBangou(cls, v):
        pattern=re.compile(r"^[0-9]{13}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid houjinBangou format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid houjinBangou format: {v}"
            raise ValueError(err_msg)
        return v


class GovernmentOrgan(Organization):
    """
    法人種別が国の機関である組織
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/org'})

    houjinBangou: Optional[str] = Field(default=None, description="""国税庁が付与する13桁の法人番号。組織の正準ID。 required にしないのは、出典管理のためグラフをソース別に分けており、 1つのエンティティの記述が複数グラフに分かれるため。SHACL検証はグラフ単位 (グラフが置換の単位)なので、グラフを跨いだ必須制約は原理的に検証できない。 「全Organizationが法人番号を持つ」ことはCQのSPARQLテストで担保する""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    organizationKindCode: Optional[str] = Field(default=None, description="""法人番号公表サイトの法人種別コード""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    prefectureName: Optional[str] = Field(default=None, description="""所在地の都道府県名""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    cityName: Optional[str] = Field(default=None, description="""所在地の市区町村名""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })

    @field_validator('houjinBangou')
    def pattern_houjinBangou(cls, v):
        pattern=re.compile(r"^[0-9]{13}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid houjinBangou format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid houjinBangou format: {v}"
            raise ValueError(err_msg)
        return v


class Ministry(GovernmentOrgan):
    """
    府省及び外局等、行政事業レビューシステム(RS)実データの所管府省庁欄・ 府省庁欄に現れるか、又は法令(府省令・規則)の発令機関としてe-Gov法令API 実データに現れる、現存する国の行政機関(名称が主キーで、府省コードは 分かる場合のみ持つ。廃止済みの名称は`old-ministries.csv`により OLD_MINISTRYの未解決参照になり、このクラスのインスタンスにはならない)
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/org'})

    ministryCode: Optional[str] = Field(default=None, description="""府省コード。分かる場合にのみ持つ任意の識別子プロパティ(裁定B12)。 現行の全府省を安定して網羅するコード出典が見つかっておらず、 Ministryの主キーは名称(skos:prefLabel)である""", json_schema_extra = { "linkml_meta": {'domain_of': ['Ministry']} })
    houjinBangou: Optional[str] = Field(default=None, description="""国税庁が付与する13桁の法人番号。組織の正準ID。 required にしないのは、出典管理のためグラフをソース別に分けており、 1つのエンティティの記述が複数グラフに分かれるため。SHACL検証はグラフ単位 (グラフが置換の単位)なので、グラフを跨いだ必須制約は原理的に検証できない。 「全Organizationが法人番号を持つ」ことはCQのSPARQLテストで担保する""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    organizationKindCode: Optional[str] = Field(default=None, description="""法人番号公表サイトの法人種別コード""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    prefectureName: Optional[str] = Field(default=None, description="""所在地の都道府県名""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    cityName: Optional[str] = Field(default=None, description="""所在地の市区町村名""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })

    @field_validator('houjinBangou')
    def pattern_houjinBangou(cls, v):
        pattern=re.compile(r"^[0-9]{13}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid houjinBangou format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid houjinBangou format: {v}"
            raise ValueError(err_msg)
        return v


class AbolishedGovernmentOrgan(GovernmentOrgan):
    """
    中央省庁等改革(2001年)等により廃止された、かつて国の行政機関で あった組織。旧省庁名の判定集合(`data/reference/old-ministries.csv`) に載る名称のうち、法令の対応表(`412CO0000000315`等)から後継が 解決できたものがこのクラスのインスタンスになる想定(C-1の `ministry_succession`参照)。解決できない名称は`OLD_MINISTRY`の 未解決参照のままで、このクラスのインスタンスにはならない (data/reference/old-ministries.csv・transform/old_ministries.py参照)
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/org'})

    succeededBy: list[str] = Field(default=..., description="""この廃止された行政機関の事務を承継した現存の行政機関。**多値** (1つ以上)——1つの旧機関の異なる部分が異なる承継先を持つ実例がある (412CO0000000315「従前の府省等の相当の新府省等を定める政令」の対応表。 例: 総理府国土庁のうち防災局は内閣府へ、それ以外は国土交通省へ)。 C-1(ministry_succession)が抽出した対応表からの解決を想定するが、 このスロット自体は出典を限定しない""", json_schema_extra = { "linkml_meta": {'domain_of': ['AbolishedGovernmentOrgan']} })
    abolitionDate: date = Field(default=..., description="""この行政機関が廃止された日付""", json_schema_extra = { "linkml_meta": {'domain_of': ['AbolishedGovernmentOrgan']} })
    houjinBangou: Optional[str] = Field(default=None, description="""国税庁が付与する13桁の法人番号。組織の正準ID。 required にしないのは、出典管理のためグラフをソース別に分けており、 1つのエンティティの記述が複数グラフに分かれるため。SHACL検証はグラフ単位 (グラフが置換の単位)なので、グラフを跨いだ必須制約は原理的に検証できない。 「全Organizationが法人番号を持つ」ことはCQのSPARQLテストで担保する""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    organizationKindCode: Optional[str] = Field(default=None, description="""法人番号公表サイトの法人種別コード""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    prefectureName: Optional[str] = Field(default=None, description="""所在地の都道府県名""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    cityName: Optional[str] = Field(default=None, description="""所在地の市区町村名""", json_schema_extra = { "linkml_meta": {'domain_of': ['Organization']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })

    @field_validator('houjinBangou')
    def pattern_houjinBangou(cls, v):
        pattern=re.compile(r"^[0-9]{13}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid houjinBangou format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid houjinBangou format: {v}"
            raise ValueError(err_msg)
        return v


class Law(Work):
    """
    法令。版(LawRevision)とは独立に、法令IDで同一性を持つ
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/law',
         'slot_usage': {'lawId': {'identifier': True, 'name': 'lawId'}}})

    lawId: str = Field(default=..., description="""e-Gov法令APIが付与する法令ID。法令の正準識別子。法令番号(lawNum)や 題名(lawTitle)は改正で変わり得るため、同一性の根拠にはしない""", json_schema_extra = { "linkml_meta": {'domain_of': ['Law', 'LawRevision']} })
    lawNum: Optional[str] = Field(default=None, description="""法令番号(例: 「令和七年厚生労働省令第十号」)。年号・法令種別・府省名等を 含む文字列で、法令番号からの府省導出(経路1)の入力になる""", json_schema_extra = { "linkml_meta": {'domain_of': ['Law']} })
    lawNumType: Optional[str] = Field(default=None, description="""e-Gov法令APIが返す法令種別ラベル(Act/CabinetOrder/MinisterialOrdinance等)。 実データには例外がある(実測済み)ため、法令種別の判定は lawNum の文字列を正とし、 このスロットはAPIの生値をそのまま保持する""", json_schema_extra = { "linkml_meta": {'domain_of': ['Law']} })
    lawTitle: Optional[str] = Field(default=None, description="""法令の題名(現行の正式名称)。題名改正で変わり得るため同一性の根拠にはしない(lawIdを使う)""", json_schema_extra = { "linkml_meta": {'domain_of': ['Law']} })
    abbrev: Optional[list[str]] = Field(default=None, description="""法令の略称。e-Gov法令APIでは0件以上の複数件があり得る""", json_schema_extra = { "linkml_meta": {'domain_of': ['Law']} })
    promulgationDate: Optional[date] = Field(default=None, description="""公布日""", json_schema_extra = { "linkml_meta": {'domain_of': ['Law']} })
    repealStatus: Optional[str] = Field(default=None, description="""廃止状態(e-Gov法令APIの repeal_status に対応する分類文字列。現行・廃止等)""", json_schema_extra = { "linkml_meta": {'domain_of': ['Law']} })
    jurisdiction: Optional[list[str]] = Field(default=None, description="""この法令を所管する府省等。法令番号からの解析(経路1)等で解決できた場合のみ設定する。 共管(複数府省の並記。例:「総理府・大蔵省令」)は府省ごとに複数のエッジを張る (設計書§7.2)。解決できない場合はこのスロットを設定せず、 core:UnresolvedReference を別に立てて unresolved_reason(OLD_MINISTRY/NO_CANDIDATE/ AMBIGUOUS)で理由を分類する(このスロット自体は未解決を表さない)""", json_schema_extra = { "linkml_meta": {'domain_of': ['Law']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class LawRevision(Event):
    """
    改正イベント。どの法令の・いつ施行の版かを表す(CQ8の器)
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/law'})

    lawId: Optional[str] = Field(default=None, description="""e-Gov法令APIが付与する法令ID。法令の正準識別子。法令番号(lawNum)や 題名(lawTitle)は改正で変わり得るため、同一性の根拠にはしない""", json_schema_extra = { "linkml_meta": {'domain_of': ['Law', 'LawRevision']} })
    amendmentLawNum: Optional[str] = Field(default=None, description="""この改正を行った法令の番号(改正法令番号)""", json_schema_extra = { "linkml_meta": {'domain_of': ['LawRevision']} })
    amendmentEnforcementDate: Optional[date] = Field(default=None, description="""この改正版の施行日。CQ8(指定時点における版の取得)の基準になる""", json_schema_extra = { "linkml_meta": {'domain_of': ['LawRevision']} })
    revisionStatus: Optional[str] = Field(default=None, description="""この改正版(LawRevision)時点での状態を表す文字列(e-Gov法令API由来)""", json_schema_extra = { "linkml_meta": {'domain_of': ['LawRevision']} })
    occurred_on: Optional[date] = Field(default=None, description="""この出来事が起きた日""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    involves_agent: Optional[str] = Field(default=None, description="""この出来事に関与した主体""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class BudgetProject(Work):
    """
    行政事業レビュー(RS)の予算事業。projectIdとfiscalYearの組で同一性を持つ (URIも両方を材料にする。上記projectIdのdocstring参照)
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/budget'})

    projectId: str = Field(default=..., description="""行政事業レビュー(RS)の予算事業ID。**単独では一意でない** — 同じ projectIdが複数の予算年度に渡って存在するため(RSは1シートに直近5年度分の 予算履歴を束ねて持つ)、BudgetProjectの実際の同一性は (projectId, fiscalYear)の組で決まる(URIも両方を材料にする。 `uris.budget_uri`)。そのため law.yaml の lawId と違い、このスロットには `identifier: true` を付けない — 付けると「projectIdだけでインスタンスが 一意に決まる」という誤った制約をスキーマに刻んでしまう。同じ複合的な 同一性を持つ law.yaml の LawRevision(lawId + amendmentEnforcementDate + amendmentLawNum)も identifier を持たない、という既存の前例に揃える (Task 7 報告書の逸脱台帳を参照。ブリーフ本文は project_id(identifier)と 書いているが、この点だけ意図的に外した)""", json_schema_extra = { "linkml_meta": {'domain_of': ['BudgetProject']} })
    projectName: Optional[str] = Field(default=None, description="""予算事業名(RSのレビューシートに記載された事業名)""", json_schema_extra = { "linkml_meta": {'domain_of': ['BudgetProject']} })
    fiscalYear: int = Field(default=..., description="""この記述が対応する事業年度(RSのレビューシート自体の年度)。 budgetAmountは同じ年度の当初予算(合計)を指す (budget_summaryの「予算年度」列がこの値と一致する集計行)。RSは 1シートに直近5年度分の予算履歴を束ねて持つが、Task 7はレビューシート 自体の年度分のみを1つのBudgetProjectとしてモデル化する(過去4年度分の 履歴は対象外。Task 7報告書の逸脱台帳を参照)""", json_schema_extra = { "linkml_meta": {'domain_of': ['BudgetProject', 'Expenditure']} })
    ministry: Optional[str] = Field(default=None, description="""所管府省庁。RSの政策所管府省庁欄(rs_columns.RS_COLのministry_name。 列5を採用する根拠はrs_columns.pyの照合記録)の名称で、Task 5の府省参照表と 突合する。突合できない場合はこのスロットを設定せず、 core:UnresolvedReference を別に立てる""", json_schema_extra = { "linkml_meta": {'domain_of': ['BudgetProject']} })
    budgetAmount: Optional[int] = Field(default=None, description="""当初予算(合計)。単位は円(RSのCSVヘッダに単位表記は無いが、実データの 最大値(約30.04兆円)から円であると確認済み。rs_columns.py照合記録 「検証8」参照)。'0'(ゼロ予算)は有効な値であり欠損ではない (rs_columns.find_budget_aggregate_row のdocstring参照)""", json_schema_extra = { "linkml_meta": {'domain_of': ['BudgetProject']} })
    basisLaw: Optional[list[str]] = Field(default=None, description="""この予算事業の根拠法令。RSの政策・施策・法令等ファイルが持つ法令IDでの 直結を主とし(e-Govスナップショットに存在することを検査し、解決できた 場合のみ設定する)、法令IDが欠落した引用は法令名・略称の完全一致で フォールバックする(曖昧照合はしない)。解決できない引用はこのスロットを 設定せず、core:UnresolvedReference を別に立てる。1つの法令を複数の 条項で引用しても、このスロットには法令単位で1エッジのみ張る (rs_columns.py照合記録「検証4」参照)""", json_schema_extra = { "linkml_meta": {'domain_of': ['BudgetProject']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


class Expenditure(MonetaryItem):
    """
    予算事業からの1件の支出(支出先1件分)。金額(amount_jpy)はMonetaryItemから 継承する(core.yamlに既存の「金額(円)」スロットがあるため、budget独自の amountスロットは追加しない。Task 7報告書の逸脱台帳を参照)。支出先の 表示名(束ね行なら「その他」等の集約ラベル)はEntityから継承する core:label(skos:prefLabel)に持たせる(recipientLabel等の専用スロットは 追加しない。理由は同上)。センチネル法人番号の行の表示名は`payeeLabel` が別に持つ(上記recipientのdocstring・B18参照)
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/budget',
         'slot_usage': {'fiscalYear': {'description': 'このExpenditureが属するBudgetProjectと同じRSレビューシートの年度 '
                                                      '(URIの構成要素でもある。`uris.expenditure_uri`)。**支出の実際の '
                                                      '支払年度ではない** — '
                                                      'task-7-review.md指摘7の実測: RS '
                                                      '2025シートの '
                                                      '支出先ファイルは実はFY2024の執行実績であり(事業ごとのΣ[23]と '
                                                      'budget_summaryのFY2024執行額[19]の比較で、中央比1.0000・完全一致 '
                                                      '32.3%を確認)、支出先ファイル自身の事業年度列は193,912行すべて '
                                                      "'2025'固定でFY2024/2025を区別する列を持たない。したがって "
                                                      '`budgetAmount`(FY2025当初予算)と`Σ '
                                                      'amount_jpy`(FY2024執行)を '
                                                      '同じBudgetProjectの下で単純に比較すると、年度の異なる2つの値を '
                                                      '比べることになる(URIのキーとリテラルの意味を分けるモデル変更は '
                                                      'Task '
                                                      '7の範囲外。controllerの裁定を仰いだ懸念として報告書に記載)',
                                       'name': 'fiscalYear'},
                        'project': {'name': 'project', 'required': True}}})

    project: str = Field(default=..., description="""この支出が属する予算事業""", json_schema_extra = { "linkml_meta": {'domain_of': ['Expenditure']} })
    recipient: Optional[str] = Field(default=None, description="""この支出の支払先。法人番号による直結を主とし、無い場合は名称正規化の 一意一致でフォールバックする。このスロットを設定しない場合が3つある: (1)「その他」等への束ね行(RSのその他支出先フラグ、またはその他支出先名。 rs_columns.py照合記録「検証7」参照) — 黙って支出自体を落とすわけではなく core:label に表示名を残す。(2) RSが「法人番号を持たない支払先」(個人・ 職員等)に使うセンチネル法人番号(`9999999999999`。法人番号の検査数字は 満たすが実在しない。task-7-review.md指摘1・B18裁定)— この場合も core:UnresolvedReferenceは立てない(照合すべき実体がそもそも存在しない ので「未解決」と呼ぶと嘘になる)代わりに`payeeLabel`に表示名を残す。 (3) 解決を試みて失敗した場合(束ね行・センチネルのいずれでもないのに 一致しない)は core:UnresolvedReference を別に立てる""", json_schema_extra = { "linkml_meta": {'domain_of': ['Expenditure']} })
    fiscalYear: int = Field(default=..., description="""このExpenditureが属するBudgetProjectと同じRSレビューシートの年度 (URIの構成要素でもある。`uris.expenditure_uri`)。**支出の実際の 支払年度ではない** — task-7-review.md指摘7の実測: RS 2025シートの 支出先ファイルは実はFY2024の執行実績であり(事業ごとのΣ[23]と budget_summaryのFY2024執行額[19]の比較で、中央比1.0000・完全一致 32.3%を確認)、支出先ファイル自身の事業年度列は193,912行すべて '2025'固定でFY2024/2025を区別する列を持たない。したがって `budgetAmount`(FY2025当初予算)と`Σ amount_jpy`(FY2024執行)を 同じBudgetProjectの下で単純に比較すると、年度の異なる2つの値を 比べることになる(URIのキーとリテラルの意味を分けるモデル変更は Task 7の範囲外。controllerの裁定を仰いだ懸念として報告書に記載)""", json_schema_extra = { "linkml_meta": {'domain_of': ['BudgetProject', 'Expenditure']} })
    payeeLabel: Optional[str] = Field(default=None, description="""支払先の表示名(RS上の名称。「個人Ａ」等)。`recipient`がセンチネル 法人番号(B18)により未設定になったExpenditureだけが持つ — 束ね行は core:label(skos:prefLabel)で表示名を既に持つため重複させず、 解決に失敗した行(NO_CANDIDATE/AMBIGUOUS)はcore:unresolved_textが 同じ役割を果たすため、このスロットは「照合対象ではないと分かっている」 行専用にする(task-7-review.md指摘1)""", json_schema_extra = { "linkml_meta": {'domain_of': ['Expenditure']} })
    role: Optional[str] = Field(default=None, description="""RSの[16]事業を行う上での役割の文言をそのまま保存する(verbatim。 解釈しない — LangStringではなく識別子的なコード値に近い扱いとして plainなstringにする。B20裁定)。「一次支出先」「間接補助事業者」 「再委託」等の値が実データに現れ、事業内の支出額を段を区別せず単純合計 すると通過金を二重に数える(task-7-review.md指摘8)。この段を集計から どう扱うか(モデル化するか、一次支出先のみを対象にするか)はTask 9の 裁定事項であり、Task 7はデータを保存するだけにとどめる""", json_schema_extra = { "linkml_meta": {'domain_of': ['Expenditure']} })
    amount_jpy: Optional[int] = Field(default=None, description="""金額(円)""", json_schema_extra = { "linkml_meta": {'domain_of': ['MonetaryItem']} })
    id: str = Field(default=..., description="""このリソースのURI""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    label: Optional[str] = Field(default=None, description="""人間が読む名称""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity'], 'slot_uri': 'skos:prefLabel'} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Entity.model_rebuild()
Agent.model_rebuild()
Work.model_rebuild()
Place.model_rebuild()
Event.model_rebuild()
MonetaryItem.model_rebuild()
Concept.model_rebuild()
UnresolvedReference.model_rebuild()
Organization.model_rebuild()
GovernmentOrgan.model_rebuild()
Ministry.model_rebuild()
AbolishedGovernmentOrgan.model_rebuild()
Law.model_rebuild()
LawRevision.model_rebuild()
BudgetProject.model_rebuild()
Expenditure.model_rebuild()
