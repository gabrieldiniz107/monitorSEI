"""Testes da publicação na biblioteca compartilhada (nomes puros + upload com Graph fake)."""
from dataclasses import replace

import pytest

from seibot import biblioteca
from seibot.classificar import agrupar_por_oficio
from seibot.models import Intimacao


def _intim(cnpj, nome="Empresa X", oficio="Ofício 600", doc_id="15955558"):
    return Intimacao(
        processo="53500.067990/2026-39", doc_id=doc_id, oficio_desc=oficio,
        destinatario=nome, documento=cnpj, documento_fmt=cnpj,
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao="Intimação para mero Conhecimento",
        data_expedicao="14/07/2026", situacao="Pendente",
    )


def _grupo(*intims):
    return agrupar_por_oficio(list(intims))[0]


# ------------------------------------------------------------------ nomes (puros)
def test_nome_da_pasta_tem_oficio_e_doc_id():
    assert biblioteca.nome_pasta(_grupo(_intim("1"), _intim("2"))) == "Ofício 600 (15955558)"


def test_nome_da_pasta_sanea_caracteres_proibidos_no_sharepoint():
    g = _grupo(replace(_intim("1"), oficio_desc='Of/ício:1*2?3"4<5>6|7\\8#9%'))
    assert not set(biblioteca.nome_pasta(g)) & set('\\/:*?"<>|#%')


def test_nome_do_oficio_espelha_a_pasta():
    g = _grupo(_intim("1"), _intim("2"))
    assert biblioteca.nome_oficio(g) == biblioteca.nome_pasta(g) + ".pdf"


def test_nome_do_anexo_segue_a_convencao_do_zip_do_sei():
    assert biblioteca.nome_anexo(2, "15944018", "Planilha") == "[2]-15944018_Planilha.pdf"
    # tipo vazio não pode gerar nome terminando em "_"
    assert biblioteca.nome_anexo(1, "123", "") == "[1]-123_Anexo.pdf"


# ------------------------------------------------------------------ publicar
class _GraphFake:
    def __init__(self):
        self.pastas, self.uploads = [], []

    def garantir_pasta(self, drive_id, caminho_pai, nome):
        self.pastas.append((drive_id, caminho_pai, nome))
        return {"webUrl": f"https://sharepoint/{nome}", "id": "pasta1"}

    def upload_arquivo(self, drive_id, caminho, conteudo, mime="x"):
        self.uploads.append((caminho, len(conteudo), mime))
        return {"id": "arq"}


def test_publicar_cria_a_pasta_sobe_tudo_e_devolve_o_link():
    g = _grupo(_intim("1"), _intim("2"), _intim("3"))
    fake = _GraphFake()
    link = biblioteca.publicar(fake, g, b"%PDF-oficio",
                               [("[1]-999_Planilha.pdf", b"anexo")], log=lambda *_: None)

    assert link == "https://sharepoint/Ofício 600 (15955558)"
    assert fake.pastas == [(biblioteca.DRIVE_DOCUMENTOS, biblioteca.PASTA_RAIZ,
                            "Ofício 600 (15955558)")]
    caminhos = [c for c, _, _ in fake.uploads]
    assert caminhos == [
        "Ofícios Jurídicos Anatel/Ofício 600 (15955558)/Ofício 600 (15955558).pdf",
        "Ofícios Jurídicos Anatel/Ofício 600 (15955558)/[1]-999_Planilha.pdf",
    ]
    assert all(mime == biblioteca.PDF_MIME for _, _, mime in fake.uploads)


def test_publicar_sem_anexos_sobe_so_o_oficio():
    fake = _GraphFake()
    biblioteca.publicar(fake, _grupo(_intim("1"), _intim("2")), b"%PDF", None,
                        log=lambda *_: None)
    assert len(fake.uploads) == 1


def test_falha_ao_subir_propaga():
    """Publicar é o ato que entrega o ofício ao cliente — não pode falhar em silêncio."""
    class _Quebra(_GraphFake):
        def upload_arquivo(self, *a, **kw):
            raise RuntimeError("Graph fora")

    with pytest.raises(RuntimeError):
        biblioteca.publicar(_Quebra(), _grupo(_intim("1"), _intim("2")), b"%PDF",
                            log=lambda *_: None)
