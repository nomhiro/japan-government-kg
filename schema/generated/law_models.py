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


linkml_meta = LinkMLMeta({'default_prefix': 'jgkglaw',
     'default_range': 'string',
     'description': '法令(Law)と、その改正イベント(LawRevision)を表すクラスとプロパティ。正準IDは '
                    '法令ID(e-Gov法令API が付与する)であり、法令番号や題名は改正で変わり得るため 同一性の根拠にしない。 '
                    'このオントロジーは日本国政府が公開するデータを第三者が構造化したものであり、日本国政府による公式なデータセットではない。',
     'id': 'https://jgkg.norr-tech.com/def/law',
     'imports': ['linkml:types', 'core', 'org'],
     'license': 'https://creativecommons.org/licenses/by/4.0/',
     'name': 'jgkg-law',
     'prefixes': {'jgkgcore': {'prefix_prefix': 'jgkgcore',
                               'prefix_reference': 'https://jgkg.norr-tech.com/def/core#'},
                  'jgkglaw': {'prefix_prefix': 'jgkglaw',
                              'prefix_reference': 'https://jgkg.norr-tech.com/def/law#'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'schema/law.yaml',
     'title': '日本政府ナレッジグラフ 法令モジュール'} )

class UnresolvedReasonEnum(str, Enum):
    """
    参照が未解決である理由の分類
    """
    NO_CANDIDATE = "NO_CANDIDATE"
    """
    候補が見つからず、政府機関の形(省/府/庁/院/委員会等)にも見えない。 抽出そのものを疑うべき警報
    """
    AMBIGUOUS = "AMBIGUOUS"
    """
    候補が複数あり一意に決められなかった
    """
    OBSOLETE_ORGANIZATION = "OBSOLETE_ORGANIZATION"
    """
    現存府省の参照表にも2001年再編の名称一覧にも無いが、政府機関の形 (省/府/庁/院/委員会等で終わる)をしている。2001年より前に廃止された 省庁名や、参照表にまだ収録されていない現存機関などが該当し得る (裁定B7。列挙ではなく形から導出するため、参照表の完全性次第で 現存機関がここに一時的に入り得る)
    """
    OLD_MINISTRY = "OLD_MINISTRY"
    """
    2001年の中央省庁再編で廃止された名称である(参照表`old-ministries.csv` に列挙。高信頼・出典あり。裁定B7でこの enum の意味をこの範囲に狭めた — それ以前に廃止された省庁は `OBSOLETE_ORGANIZATION` に分類する)
    """



class Entity(ConfiguredBaseModel):
    """
    本KGが扱うすべての事物の基底
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True, 'from_schema': 'https://jgkg.norr-tech.com/def/core'})

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
        pattern=re.compile(r"^\d{13}$")
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
        pattern=re.compile(r"^\d{13}$")
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
    府省及び外局等、行政事業レビューシステム(RS)実データの所管府省庁欄・ 府省庁欄に現れる国の行政機関(裁定B12・B16。名称が主キーで、 府省コードは分かる場合のみ持つ)
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
        pattern=re.compile(r"^\d{13}$")
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
Law.model_rebuild()
LawRevision.model_rebuild()
