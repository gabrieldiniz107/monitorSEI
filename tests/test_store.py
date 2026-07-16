"""Testes do dedup SQLite (IntimacoesStore)."""
from seibot.models import Intimacao
from seibot.store import IntimacoesStore


def _intim(chave_cnpj="111"):
    return Intimacao(
        processo="P1", doc_id="10", oficio_desc="Ofício 10",
        destinatario="Empresa", documento=chave_cnpj, documento_fmt=chave_cnpj,
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao="Requerimento de Informações",
        data_expedicao="14/07/2026", situacao="Pendente",
    )


def test_marcar_e_checar(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    assert store.ja_visto(i.chave) is False
    store.marcar_visto(i, "individual")
    assert store.ja_visto(i.chave) is True
    assert store.contar() == 1


def test_idempotente(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    store.marcar_visto(i, "individual")
    store.marcar_visto(i, "individual")
    assert store.contar() == 1


def test_marcar_lote_baseline(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    ints = [_intim("111"), _intim("222"), _intim("333")]
    n = store.marcar_lote(ints)
    assert n == 3
    assert store.contar() == 3
    assert all(store.ja_visto(i.chave) for i in ints)
