"""Agrupamento de intimações por ofício → coletivo vs individual."""
from __future__ import annotations

from collections import OrderedDict

from .models import Grupo, Intimacao


def agrupar_por_oficio(intims: list[Intimacao]) -> list[Grupo]:
    """Agrupa por (processo, doc_id). Mesmo ofício p/ várias empresas = coletivo.

    Preserva a ordem de primeira aparição dos grupos.
    """
    baldes: "OrderedDict[tuple[str, str], list[Intimacao]]" = OrderedDict()
    for i in intims:
        baldes.setdefault((i.processo, i.doc_id), []).append(i)

    grupos: list[Grupo] = []
    for (processo, doc_id), itens in baldes.items():
        primeiro = itens[0]
        grupos.append(Grupo(
            processo=processo,
            doc_id=doc_id,
            oficio_desc=primeiro.oficio_desc,
            tipo_intimacao=primeiro.tipo_intimacao,
            data_expedicao=primeiro.data_expedicao,
            situacao=primeiro.situacao,
            destinatarios=tuple(itens),
        ))
    return grupos
