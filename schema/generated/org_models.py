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


linkml_meta = LinkMLMeta({'default_prefix': 'jgkgorg',
     'default_range': 'string',
     'description': '組織(府省・法人)を表すクラスとプロパティ。正準IDは法人番号。 '
                    'このオントロジーは日本国政府が公開するデータを第三者が構造化したものであり、日本国政府による公式なデータセットではない。',
     'id': 'https://jgkg.norr-tech.com/def/org',
     'imports': ['linkml:types', 'core'],
     'license': 'https://creativecommons.org/licenses/by/4.0/',
     'name': 'jgkg-org',
     'prefixes': {'jgkgcore': {'prefix_prefix': 'jgkgcore',
                               'prefix_reference': 'https://jgkg.norr-tech.com/def/core#'},
                  'jgkgorg': {'prefix_prefix': 'jgkgorg',
                              'prefix_reference': 'https://jgkg.norr-tech.com/def/org#'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'schema': {'prefix_prefix': 'schema',
                             'prefix_reference': 'http://schema.org/'},
                  'skos': {'prefix_prefix': 'skos',
                           'prefix_reference': 'http://www.w3.org/2004/02/skos/core#'}},
     'source_file': 'schema/org.yaml',
     'title': '日本政府ナレッジグラフ 組織モジュール'} )

class UnresolvedReasonEnum(str, Enum):
    """
    参照が未解決である理由の分類
    """
    NO_CANDIDATE = "NO_CANDIDATE"
    """
    候補が見つからなかった
    """
    AMBIGUOUS = "AMBIGUOUS"
    """
    候補が複数あり一意に決められなかった
    """
    OBSOLETE_ORGANIZATION = "OBSOLETE_ORGANIZATION"
    """
    旧省庁名など、現存しない組織を指している
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
    府省。府省コードで識別できる国の機関
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://jgkg.norr-tech.com/def/org'})

    ministryCode: Optional[str] = Field(default=None, description="""GIFコードリストの府省コード""", json_schema_extra = { "linkml_meta": {'domain_of': ['Ministry']} })
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
