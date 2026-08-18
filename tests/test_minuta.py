"""Testes da minuta de dilação (Fase 5).

O montador é puro: os casos abaixo comparam a peça com o template real usado pelo Jurídico
(`BKUP_TELECOM_Pedido_Dilacao_Prazo_RI_II.pdf`, proc 53532.000310/2026-20) e cobrem o caso
sem dossiê guardado, em que tudo o que falta tem de virar lacuna visível — nunca invenção.
"""
import json
from datetime import date

from seibot import minuta as m
from seibot.dilacao import Analise

# dossiê equivalente ao do template
ANALISE = Analise(
    admite=True,
    fundamento="no item 5 do Requerimento de Informações RI-II",
    dias=10,
    ref_documento="Requerimento de Informações RI-II (SEI nº 15716436)",
    orgao=("Gerência Regional nos Estados de Pernambuco, Paraíba e Alagoas – GR06",
           "Coordenação de Fiscalização Regulatória – GR06FI1"),
    norma="Regulamento de Fiscalização Regulatória, aprovado pela Resolução nº 746, "
          "de 22 de junho de 2021",
    justificativa=("A amostra abrange equipamentos de cinco exercícios fiscais.",
                   "Remanescem documentos cuja segunda via depende de terceiros."),
    cidade="Rio das Antas",
)

DADOS = {
    "processo": "53532.000310/2026-20",
    "oficio_desc": "Ofício 99",
    "doc_id": "15736628",
    "empresa": "Bkup Telecom Ltda",
    "cnpj": "09153816000120",
    "data_ciencia": "02/06/2026",
    "data_limite": "16/06/2026",
    "prazo_dias": 10,
    "prazo_unidade": "dias",
    "protocolos": {"15739322": "Certidão de Intimação Cumprida",
                   "15716436": "Requerimento de Informações"},
    "cidade_cadastro": "RIO DAS ANTAS",
    "assinante": "Rodrigo Silva Oliveira",
    "assinante_cargo": "Procurador",
}


# ------------------------------------------------------------------ helpers puros
def test_numero_por_extenso_cobre_o_intervalo_de_prazos():
    assert m.por_extenso(10) == "dez"
    assert m.por_extenso(15) == "quinze"
    assert m.por_extenso(20) == "vinte"
    assert m.por_extenso(45) == "quarenta e cinco"
    assert m.por_extenso(120) == ""   # fora da faixa: melhor sem extenso do que errado


def test_dias_por_extenso_preserva_a_unidade():
    """Dia útil ≠ dia corrido — a distinção importa juridicamente."""
    assert m.dias_por_extenso(10, "dias") == "10 (dez) dias"
    assert m.dias_por_extenso(20, "dias úteis") == "20 (vinte) dias úteis"


def test_cidade_mantem_preposicoes_minusculas():
    """O cadastro guarda em caixa alta; title-case cru geraria 'Rio Das Antas'."""
    assert m.cidade_formatada("RIO DAS ANTAS") == "Rio das Antas"
    assert m.cidade_formatada("SAO LUIS DE MONTES BELOS") == "Sao Luis de Montes Belos"
    assert m.cidade_formatada("") == ""


def test_cnpj_formatado():
    assert m.cnpj_formatado("09153816000120") == "09.153.816/0001-20"
    assert m.cnpj_formatado("123") == "123"   # não inventa máscara para lixo


def test_certidao_sai_da_lista_de_protocolos():
    assert m.certidao_de(DADOS["protocolos"]) == "15739322"
    assert m.certidao_de({"1": "Ofício 99"}) == ""


def test_data_por_extenso():
    assert m.data_por_extenso(date(2026, 6, 12)) == "12 de junho de 2026"


# ------------------------------------------------------------------ minuta completa
def test_minuta_completa_reproduz_a_estrutura_do_template():
    peca = m.montar(DADOS, ANALISE, hoje=date(2026, 6, 12))
    t = peca.texto
    assert peca.lacunas == ()
    for esperado in (
        "À AGÊNCIA NACIONAL DE TELECOMUNICAÇÕES – ANATEL",
        "Coordenação de Fiscalização Regulatória – GR06FI1",
        "Processo nº 53532.000310/2026-20",
        "Assunto: Pedido de dilação de prazo",
        "BKUP TELECOM LTDA",
        "09.153.816/0001-20",
        "item 5 do Requerimento de Informações RI-II",
        "Resolução nº 746",
        "I – DA TEMPESTIVIDADE",
        "cumprida por consulta direta em 02/06/2026",
        "Certidão de Intimação Cumprida (SEI nº 15739322)",
        "prazo de 10 (dez) dias",
        "não suspende nem interrompe",
        "II – DA JUSTIFICATIVA",
        "III – DO PEDIDO",
        "por 10 (dez) dias",
        "Nestes termos, pede deferimento.",
        "Rio das Antas, 12 de junho de 2026.",
        "Rodrigo Silva Oliveira",
        "Procurador",
    ):
        assert esperado in t, esperado


def test_justificativa_do_llm_entra_como_paragrafos():
    peca = m.montar(DADOS, ANALISE, hoje=date(2026, 6, 12))
    corpo = [txt for _, txt in peca.paragrafos]
    assert "A amostra abrange equipamentos de cinco exercícios fiscais." in corpo
    assert "Remanescem documentos cuja segunda via depende de terceiros." in corpo


# ------------------------------------------------------------------ sem dossiê
def test_sem_analise_a_minuta_sai_com_lacunas_marcadas():
    """Decisão do usuário: gerar mesmo sem o texto do ofício. O que falta vira lacuna
    visível — uma peça revisável, nunca um dado inventado."""
    peca = m.montar(DADOS)          # análise vazia
    t = peca.texto
    assert peca.lacunas, "sem análise tem de haver o que preencher"
    assert "[PREENCHER: unidade da Anatel (Gerência/Coordenação)]" in t
    assert "[PREENCHER: fundamento que autoriza a dilação (item do ofício/RI)]" in t
    assert "[PREENCHER: justificativa do pedido" in t
    # o que o bot SABE continua preenchido
    assert "53532.000310/2026-20" in t and "BKUP TELECOM LTDA" in t


def test_sem_data_de_ciencia_vira_lacuna():
    """`--modo completo` não grava data de ciência (a intimação já estava cumprida):
    carimbar 'hoje' mentiria numa peça que alega tempestividade."""
    dados = dict(DADOS, data_ciencia="")
    peca = m.montar(dados, ANALISE, hoje=date(2026, 6, 12))
    assert "[PREENCHER: data da ciência]" in peca.texto
    assert "data da ciência" in peca.lacunas


def test_sem_dias_do_oficio_pede_o_prazo_original():
    """Teto do template: 'período não superior ao originalmente concedido'."""
    peca = m.montar(DADOS, Analise(), hoje=date(2026, 6, 12))
    assert peca.dias_pedidos == 10
    assert "por 10 (dez) dias" in peca.texto


def test_dias_do_oficio_prevalecem_sobre_o_prazo_original():
    peca = m.montar(dict(DADOS, prazo_dias=15), Analise(dias=5), hoje=date(2026, 6, 12))
    assert peca.dias_pedidos == 5


def test_cidade_do_llm_prevalece_sobre_a_do_cadastro():
    """O cadastro é sem acento; a grafia correta vem do LLM."""
    peca = m.montar(dict(DADOS, cidade_cadastro="SAO PAULO"),
                    Analise(cidade="São Paulo"), hoje=date(2026, 6, 12))
    assert "São Paulo, 12 de junho de 2026." in peca.texto


def test_sem_municipio_cai_na_cidade_padrao():
    peca = m.montar(dict(DADOS, cidade_cadastro="", cidade_padrao="Curitiba"),
                    Analise(), hoje=date(2026, 6, 12))
    assert "Curitiba, 12 de junho de 2026." in peca.texto


def test_sem_municipio_nem_padrao_vira_lacuna():
    peca = m.montar(dict(DADOS, cidade_cadastro="", cidade_padrao=""), Analise(),
                    hoje=date(2026, 6, 12))
    assert "[PREENCHER: cidade]" in peca.texto and "cidade do fecho" in peca.lacunas


# ------------------------------------------------------------------ docx
def test_docx_e_um_arquivo_word_valido_com_o_texto_dentro():
    import io
    import zipfile

    peca = m.montar(DADOS, ANALISE, hoje=date(2026, 6, 12))
    bruto = m.para_docx(peca)
    assert bruto[:2] == b"PK"          # docx é um zip
    with zipfile.ZipFile(io.BytesIO(bruto)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "PEDIDO DE DILAÇÃO DE PRAZO" in xml
    assert "Rodrigo Silva Oliveira" in xml


def test_nome_do_arquivo_sanea_o_nome_da_empresa():
    peca = m.montar(dict(DADOS, empresa='Bkup/Telecom:Ltda'), ANALISE)
    nome = m.nome_arquivo(peca, "15736628")
    assert nome.endswith(".docx") and not set(nome) & set('\\/:*?"<>|#%')
    assert "15736628" in nome


# ------------------------------------------------------------------ cola (monitor.montar_minuta)
class _ClientesFake:
    def __init__(self, info=None):
        self._info = info

    def info(self, cnpj):
        return self._info


class _LLMFake:
    """Registra o prompt e devolve um JSON fixo."""

    def __init__(self, payload):
        self._payload = payload
        self.chamadas = []
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kw):
        self.chamadas.append(kw)
        msg = type("M", (), {"content": self._payload})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


def _linha(**over):
    base = {
        "chave": "P|10|09153816000120",
        "processo": "53532.000310/2026-20", "doc_id": "15736628",
        "oficio_desc": "Ofício 99", "empresa": "Bkup Telecom Ltda",
        "cnpj": "09153816000120", "data_limite": "16/06/2026",
        "prazo_dias": 10, "prazo_unidade": "dias", "data_ciencia": "02/06/2026",
        "oficio_texto": "texto real do ofício", "protocolos_json":
            '{"15739322": "Certidão de Intimação Cumprida"}',
    }
    base.update(over)
    return base


def _cfg():
    from seibot.config import Config
    return Config(openai_api_key="fake", dilacao_assinante="Rodrigo Silva Oliveira",
                  dilacao_assinante_cargo="Procurador", dilacao_cidade_padrao="")


def test_montar_minuta_leva_ao_llm_o_que_o_bot_ja_sabe():
    from seibot import clientes as C, monitor

    llm = _LLMFake(json.dumps({"fundamento": "item 5 do RI-II", "dias": 10,
                               "justificativa": ["porque sim"]}))
    info = C.ClienteInfo(cnpj="09153816000120", em_base=True, razao="Bkup Telecom Ltda",
                         municipio="RIO DAS ANTAS", uf="SC")
    peca = monitor.montar_minuta(_cfg(), _ClientesFake(info), _linha(),
                                 client_llm=llm, log=lambda *_: None)
    prompt = llm.chamadas[0]["messages"][1]["content"]
    assert "53532.000310/2026-20" in prompt and "Bkup Telecom Ltda" in prompt
    assert "RIO DAS ANTAS, SC" in prompt          # praça do cadastro
    assert "10 dias" in prompt                     # prazo original
    assert "Certidão de Intimação Cumprida" in prompt
    assert "item 5 do RI-II" in peca.texto
    # sem cidade do LLM, cai no cadastro com a caixa consertada
    assert "Rio das Antas," in peca.texto


def test_montar_minuta_sem_texto_guardado_nao_chama_o_llm_e_marca_lacunas():
    from seibot import monitor

    llm = _LLMFake("{}")
    peca = monitor.montar_minuta(_cfg(), _ClientesFake(None), _linha(oficio_texto=""),
                                 client_llm=llm, log=lambda *_: None)
    assert llm.chamadas == []
    assert peca.lacunas and "[PREENCHER" in peca.texto
    assert peca.dias_pedidos == 10                # ainda assim pede o prazo original


def test_montar_minuta_tolera_protocolos_json_corrompido():
    from seibot import monitor

    llm = _LLMFake(json.dumps({"dias": 10, "justificativa": ["ok"]}))
    peca = monitor.montar_minuta(_cfg(), _ClientesFake(None),
                                 _linha(protocolos_json="{isto não é json"),
                                 client_llm=llm, log=lambda *_: None)
    assert "Certidão de Intimação Cumprida" not in peca.texto   # sem a prova, segue sem ela
    assert peca.dias_pedidos == 10


# --------------------------------------------- regressões achadas no ensaio real (18/08/2026)
def test_referencia_nao_duplica_o_numero_sei():
    """O LLM devolve 'Ofício 498 (SEI nº 15963368)' pronto; concatenar geraria
    '(SEI nº X) (SEI nº Y)' — visto no primeiro ensaio com ofício real."""
    peca = m.montar(DADOS, ANALISE, hoje=date(2026, 6, 12))
    ref = [t for _, t in peca.paragrafos if t.startswith("Ref.:")][0]
    assert ref.count("SEI nº") == 1
    assert "(SEI nº 15716436) (SEI nº 15736628)" not in peca.texto


def test_referencia_ganha_o_sei_quando_nao_tem_nenhum():
    peca = m.montar(DADOS, Analise(ref_documento="Ofício 99"), hoje=date(2026, 6, 12))
    assert "Ref.: Ofício 99 (SEI nº 15736628)" in peca.texto


def test_norma_entra_sem_artigo_fixo_que_erraria_a_concordancia():
    """'nas disposições do Lei nº 9.998' saiu no ensaio real. A norma tanto é 'Lei…'
    quanto 'Regulamento…' — artigo fixo erra metade dos casos."""
    peca = m.montar(DADOS, Analise(fundamento="art. 6º-A", norma="Lei nº 9.998, de 2000"),
                    hoje=date(2026, 6, 12))
    assert "e em Lei nº 9.998, de 2000" in peca.texto  # sem preposição do modelo, entra "em"
    assert "do Lei" not in peca.texto


def test_norma_igual_ao_fundamento_nao_e_repetida():
    peca = m.montar(DADOS, Analise(fundamento="inciso IV do art. 6º-A da Lei nº 9.998",
                                   norma="Lei nº 9.998"), hoje=date(2026, 6, 12))
    assert peca.texto.count("Lei nº 9.998") == 1


def test_cidade_do_llm_em_caixa_alta_e_corrigida():
    """O modelo às vezes ecoa o cadastro: 'BELO HORIZONTE, 18 de agosto' saiu no ensaio."""
    peca = m.montar(dict(DADOS, cidade_cadastro="BELO HORIZONTE"),
                    Analise(cidade="BELO HORIZONTE"), hoje=date(2026, 6, 12))
    assert "Belo Horizonte, 12 de junho de 2026." in peca.texto


def test_cidade_ja_acentuada_do_llm_passa_intacta():
    peca = m.montar(DADOS, Analise(cidade="São Luís de Montes Belos"),
                    hoje=date(2026, 6, 12))
    assert "São Luís de Montes Belos, 12 de junho de 2026." in peca.texto


def test_preposicao_do_fundamento_e_do_modelo_com_rede_de_seguranca():
    """O artigo depende do substantivo ('no item 5', mas 'nas orientações') — quem escolhe
    é o modelo. Sem preposição nenhuma entra 'em', que nunca erra concordância.
    (Regressão: saiu 'com fundamento no orientações constantes do Manual'.)"""
    assert m.com_preposicao("no item 5 do RI-II") == "no item 5 do RI-II"
    assert m.com_preposicao("nas orientações do Manual") == "nas orientações do Manual"
    assert m.com_preposicao("orientações do Manual") == "em orientações do Manual"
    assert m.com_preposicao("") == ""

    peca = m.montar(DADOS, Analise(fundamento="orientações constantes do Manual anexo"),
                    hoje=date(2026, 6, 12))
    assert "com fundamento em orientações constantes do Manual anexo" in peca.texto
    assert "com fundamento no orientações" not in peca.texto


def test_fundamento_com_artigo_do_modelo_nao_ganha_em_redundante():
    peca = m.montar(DADOS, Analise(fundamento="no item 5 do RI-II"), hoje=date(2026, 6, 12))
    assert "com fundamento no item 5 do RI-II" in peca.texto


def test_docx_nasce_em_portugues_do_brasil():
    """O template do python-docx vem em inglês: sem isto o Word marca CADA palavra em
    português como erro e a minuta chega ao Jurídico coberta de vermelho."""
    import io
    import zipfile

    peca = m.montar(DADOS, ANALISE, hoje=date(2026, 6, 12))
    with zipfile.ZipFile(io.BytesIO(m.para_docx(peca))) as z:
        estilos = z.read("word/styles.xml").decode("utf-8")
    assert 'w:val="pt-BR"' in estilos
    # nem no docDefaults (a raiz) pode sobrar inglês: texto que não herde de Normal
    # voltaria a ser corrigido em inglês
    assert "en-US" not in estilos


def test_minuta_registra_se_o_oficio_admite_dilacao():
    """`admite` existia mas não era usado — defeito achado ao validar um caso real de
    Notificação de Lançamento tributária, em que o remédio é impugnação, não dilação."""
    assert m.montar(DADOS, ANALISE).admite_dilacao is True
    assert m.montar(DADOS, Analise(dias=10, admite=False)).admite_dilacao is False
    # sem dossiê não dá para afirmar nem negar
    assert m.montar(DADOS).admite_dilacao is None
