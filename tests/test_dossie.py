"""Testes do cache em disco do ofício + anexos (insumo da pasta da minuta, Fase 5).

Existe porque o comando `prazos` — que gera a minuta — **não acessa o SEI**: os bytes só
estão disponíveis durante a tratativa, quando o bot já está logado.
"""
import os

from seibot import dossie


def test_base_deriva_do_caminho_do_banco(tmp_path):
    """Os dois vivem no mesmo volume; derivar evita mais uma variável de ambiente."""
    assert dossie.base_de("state/intimacoes.db") == os.path.join("state", "dossies")
    assert dossie.base_de("intimacoes.db") == os.path.join(".", "dossies")


def test_guarda_e_recupera_na_ordem_de_conferencia(tmp_path):
    db = str(tmp_path / "t.db")
    dossie.guardar(db, "16126557", [
        ("1-15716436_Planilha.pdf", b"%PDF-anexo"),
        ("0-Ofício 884 (16126557).pdf", b"%PDF-oficio"),
    ], log=lambda *_: None)

    lidos = dossie.carregar(db, "16126557", log=lambda *_: None)
    # o ofício vem primeiro: o prefixo "0-" existe para isso
    assert [n for n, _ in lidos] == ["0-Ofício 884 (16126557).pdf", "1-15716436_Planilha.pdf"]
    assert lidos[0][1] == b"%PDF-oficio"


def test_sem_nada_guardado_devolve_lista_vazia(tmp_path):
    """Ofício tratado antes desta mudança: a pasta sai só com o .docx."""
    assert dossie.carregar(str(tmp_path / "t.db"), "999", log=lambda *_: None) == []


def test_conteudo_vazio_nao_vira_arquivo(tmp_path):
    db = str(tmp_path / "t.db")
    n = dossie.guardar(db, "1", [("vazio.pdf", b""), ("ok.pdf", b"%PDF")],
                       log=lambda *_: None)
    assert n == 1
    assert [nome for nome, _ in dossie.carregar(db, "1", log=lambda *_: None)] == ["ok.pdf"]


def test_nomes_sao_seguros_para_disco_e_para_sharepoint(tmp_path):
    of = dossie.nome_oficio("Of/ício: 99*", "123")
    anx = dossie.nome_anexo(1, "456", 'Planilha "A"')
    for nome in (of, anx):
        assert not set(nome) & set('\\/:*?"<>|#%')
        assert nome.endswith(".pdf")
    assert of.startswith("0-") and anx.startswith("1-")


def test_guardar_nunca_levanta(tmp_path):
    """É insumo de uma peça futura, gravado depois da ciência — não pode derrubar a
    tratativa já concluída."""
    # caminho impossível: o "banco" é um arquivo, então a pasta não pode ser criada dentro
    arquivo = tmp_path / "arquivo"
    arquivo.write_text("x")
    n = dossie.guardar(str(arquivo / "sub" / "t.db"), "1", [("a.pdf", b"x")],
                       log=lambda *_: None)
    assert n == 0


def test_doc_id_estranho_nao_escapa_da_pasta(tmp_path):
    db = str(tmp_path / "t.db")
    assert dossie.pasta(db, "../../etc") == os.path.join(dossie.base_de(db), "sem_doc_id")
    assert dossie.pasta(db, "16126557").endswith("16126557")
