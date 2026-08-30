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


linkml_meta = LinkMLMeta({'default_prefix': 'jgkgcore',
     'default_range': 'string',
     'description': '6軸(誰が/何を/どこで/いつ/いくらで/何について)の基底クラスと、 '
                    '出典を表す用語を定義する。ドメイン固有のクラスは各ドメインモジュールで このモジュールを import して継承する。 '
                    'このオントロジーは日本国政府が公開するデータを第三者が構造化したものであり、日本国政府による公式なデータセットではない。',
     'id': 'https://jgkg.norr-tech.com/def/core',
     'imports': ['linkml:types'],
     'license': 'https://creativecommons.org/licenses/by/4.0/',
     'name': 'jgkg-core',
     'prefixes': {'dcterms': {'prefix_prefix': 'dcterms',
                              'prefix_reference': 'http://purl.org/dc/terms/'},
                  'jgkgcore': {'prefix_prefix': 'jgkgcore',
                               'prefix_reference': 'https://jgkg.norr-tech.com/def/core#'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'prov': {'prefix_prefix': 'prov',
                           'prefix_reference': 'http://www.w3.org/ns/prov#'},
                  'rdf': {'prefix_prefix': 'rdf',
                          'prefix_reference': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'},
                  'schema': {'prefix_prefix': 'schema',
                             'prefix_reference': 'http://schema.org/'},
                  'skos': {'prefix_prefix': 'skos',
                           'prefix_reference': 'http://www.w3.org/2004/02/skos/core#'}},
     'source_file': 'schema/core.yaml',
     'title': '日本政府ナレッジグラフ コアスキーマ',
     'types': {'LangString': {'base': 'str',
                              'description': '言語タグ付きの文字列。人が読む名称や文章に使う。 '
                                             '識別子やコードには使わない(それらは言語に依存しないため plain な '
                                             'string を使う)。 '
                                             'この区別をスキーマに明示することで、どの値が言語依存かがモデルから読み取れる。',
                              'from_schema': 'https://jgkg.norr-tech.com/def/core',
                              'name': 'LangString',
                              'uri': 'rdf:langString'}}} )

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

    amount_jpy: Optional[int] = Field(default=None, title="金額(円)", description="""金額(円)""", json_schema_extra = { "linkml_meta": {'domain_of': ['MonetaryItem']} })
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
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/core',
         'title': '対応先が特定できなかった記述'})

    unresolved_text: Optional[str] = Field(default=None, title="元の記述", description="""正準IDに解決できなかった元の参照文字列""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedReference']} })
    unresolved_reason: Optional[UnresolvedReasonEnum] = Field(default=None, title="特定できなかった理由", description="""解決できなかった理由""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedReference']} })
    unresolved_key: Optional[str] = Field(default=None, title="元データでの識別子", description="""解決できなかった参照の、ソース側のキー(府省コード等)。ドメイン固有の プロパティを UnresolvedReference に足すと閉じたSHACLシェイプに違反するため、 汎用のキーとしてここで受ける""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedReference']} })
    unresolvedFor: Optional[str] = Field(default=None, title="この記述が関わる項目", description="""この未解決参照が生じた主体(参照元のエンティティ)。CQ9等が未解決ノード からその主体へグラフパターンで辿れるようにするための辺(URIの再構成を 要しない。裁定B8)。方向はUnresolvedReference→主体(逆向きにすると、 未解決を持ち得る全クラスがこのプロパティを宣言する必要が生じ、閉じた シェイプが増殖する。unresolved_keyを汎用スロットとしてUnresolvedReference 側に置いたのと同じ設計)。**必須にしない** — 主体を特定できない未解決 (例: emit_ministriesの未解決府省。参照表の1行がどの組織にも対応しない だけで、特定の「この記述の主体」が無い)を壊さないため""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedReference']} })
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
