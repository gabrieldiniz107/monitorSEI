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


# ------------------------------------------------------------------ Fase 5: minuta (INTERNO)
class _GraphCaminho(_GraphFake):
    """Fake que também sabe criar árvore de pastas (garantir_caminho é do Graph real)."""

    def __init__(self):
        super().__init__()
        self.caminhos, self.drives_upload = [], []

    def garantir_caminho(self, drive_id, caminho):
        self.caminhos.append((drive_id, caminho))
        return {"webUrl": f"https://sharepoint/{caminho}", "id": "pasta"}

    def upload_arquivo(self, drive_id, caminho, conteudo, mime="x"):
        self.drives_upload.append(drive_id)
        super().upload_arquivo(drive_id, caminho, conteudo, mime)
        return {"webUrl": f"https://sharepoint/{caminho}", "id": "arq"}


def test_minuta_vai_para_a_biblioteca_INTERNA_nunca_para_a_dos_clientes():
    """A pasta da Fase 4 é compartilhada com os clientes; minuta é peça em elaboração."""
    assert biblioteca.DRIVE_GESTAO_INTEGRADA != biblioteca.DRIVE_DOCUMENTOS
    fake = _GraphCaminho()
    biblioteca.publicar_minuta(fake, "Ofício 99", "15736628", "Pedido.docx", b"PK-docx",
                               log=lambda *_: None)
    assert all(drive == biblioteca.DRIVE_GESTAO_INTEGRADA for drive, _ in fake.caminhos)
    assert fake.drives_upload == [biblioteca.DRIVE_GESTAO_INTEGRADA]
    assert biblioteca.DRIVE_DOCUMENTOS not in fake.drives_upload


def test_publicar_minuta_monta_o_caminho_e_devolve_o_link_do_ARQUIVO():
    fake = _GraphCaminho()
    pub = biblioteca.publicar_minuta(fake, "Ofício 99", "15736628",
                                     "Pedido de Dilacao de Prazo - Bkup.docx",
                                     b"PK-docx", log=lambda *_: None)
    esperado = ("Jurídico/Minutas de Dilação de Prazo/Ofício 99 (15736628)/"
                "Pedido de Dilacao de Prazo - Bkup.docx")
    assert [c for c, _, _ in fake.uploads] == [esperado]
    # a árvore inteira é garantida (a raiz 'Jurídico/…' ainda não existia na biblioteca)
    assert fake.caminhos == [(biblioteca.DRIVE_GESTAO_INTEGRADA,
                              "Jurídico/Minutas de Dilação de Prazo/Ofício 99 (15736628)")]
    # os DOIS links vão para o Teams (pedido do usuário): o arquivo abre direto no Word
    # para revisar; a pasta é onde ficam as versões ajustadas e o resto do caso.
    assert pub.arquivo_url.endswith(".docx")
    assert pub.pasta_url.endswith("Ofício 99 (15736628)")
    assert not pub.pasta_url.endswith(".docx")


def test_publicar_minuta_usa_o_mime_de_docx():
    fake = _GraphCaminho()
    biblioteca.publicar_minuta(fake, "Ofício 99", "1", "x.docx", b"PK", log=lambda *_: None)
    assert fake.uploads[0][2] == biblioteca.DOCX_MIME


def test_minuta_leva_o_oficio_e_os_anexos_para_a_mesma_pasta():
    """A pasta é o dossiê do caso: quem revisa confere a minuta contra o ofício sem voltar
    ao SEI (pedido do usuário, 18/08/2026)."""
    fake = _GraphCaminho()
    pub = biblioteca.publicar_minuta(
        fake, "Ofício 99", "15736628", "Pedido.docx", b"PK-docx",
        [("0-Ofício 99 (15736628).pdf", b"%PDF-of"), ("1-15716436_Planilha.pdf", b"%PDF-anx")],
        log=lambda *_: None)

    base = "Jurídico/Minutas de Dilação de Prazo/Ofício 99 (15736628)"
    assert [c for c, _, _ in fake.uploads] == [
        f"{base}/Pedido.docx",
        f"{base}/0-Ofício 99 (15736628).pdf",
        f"{base}/1-15716436_Planilha.pdf",
    ]
    assert pub.extras == 2
    # o ofício e os anexos são PDF; só a minuta é docx
    assert [mime for _, _, mime in fake.uploads] == [biblioteca.DOCX_MIME,
                                                     biblioteca.PDF_MIME, biblioteca.PDF_MIME]


def test_anexo_que_falha_nao_custa_a_minuta():
    """A minuta sobe primeiro: um anexo grande demais (limite de ~4 MB do upload simples)
    não pode deixar o Jurídico sem a peça na véspera do vencimento."""
    class _QuebraNoSegundo(_GraphCaminho):
        def upload_arquivo(self, drive_id, caminho, conteudo, mime="x"):
            if caminho.endswith(".pdf"):
                raise RuntimeError("413 payload too large")
            return super().upload_arquivo(drive_id, caminho, conteudo, mime)

    fake = _QuebraNoSegundo()
    pub = biblioteca.publicar_minuta(fake, "Ofício 99", "1", "Pedido.docx", b"PK",
                                     [("0-of.pdf", b"%PDF")], log=lambda *_: None)
    assert pub.arquivo_url.endswith(".docx") and pub.extras == 0
