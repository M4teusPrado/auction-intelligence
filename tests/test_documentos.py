import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao import documentos
from captacao.aplicacao import ficha
from test_triagem import base_teste


def pdf_com_texto(paginas):
    """Monta um PDF mínimo e válido, com uma linha de texto por página (fonte Helvetica)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for texto in paginas:
        conteudo = "BT /F1 11 Tf 40 760 Td (" + texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj ET"
        dados = conteudo.encode("cp1252")
        objs.append(b"<< /Length %d >>\nstream\n" % len(dados) + dados + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    saida, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(saida))
        corpo = o if isinstance(o, bytes) else o.encode("latin-1")
        saida += f"{i} 0 obj\n".encode() + corpo + b"\nendobj\n"
    xref = len(saida)
    saida += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    saida += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    saida += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(saida)


class Busca(unittest.TestCase):
    def test_acha_termos_sem_acento_e_mantem_trecho_original(self):
        paginas = ["Matrícula 123. R.4 PENHORA em favor de Fulano, processo 001.", "",
                   "AV.5 Cancelamento da penhora do R.4. Consolidação da propriedade em nome da CAIXA."]
        achados = documentos.buscar(paginas)
        rotulos = {(a["rotulo"], a["pagina"]) for a in achados}
        self.assertIn(("Penhora, arresto ou sequestro", 1), rotulos)
        self.assertIn(("Penhora, arresto ou sequestro", 3), rotulos)
        self.assertIn(("Cancelamento (pode anular um ônus acima)", 3), rotulos)
        self.assertIn(("Consolidação da propriedade", 3), rotulos)
        p = next(a for a in achados if a["pagina"] == 1 and a["termo"] == "penhora")
        self.assertEqual(p["achado"], "PENHORA")                  # trecho com a grafia do documento
        self.assertTrue(p["antes"].endswith("R.4 "))
        self.assertTrue(p["depois"].startswith(" em favor"))
        c = next(a for a in achados if a["termo"] == "consolidacao da propriedade")
        self.assertEqual(c["achado"], "Consolidação da propriedade")

    def test_palavra_inteira(self):
        self.assertEqual(documentos.buscar(["despenhorado e iptuxyz"]), [])
        itens = {a["item"] for a in documentos.buscar(["Débitos de IPTU e condomínio por conta do arrematante."])}
        self.assertEqual(itens, {"iptu", "condominio", "edital"})

    def test_limite_por_termo(self):
        self.assertEqual(len(documentos.buscar(["hipoteca " * 20])), documentos.POR_TERMO_MAX)


@unittest.skipUnless(documentos.leitura_ligada(), "pypdf não instalado (rode com .venv/bin/python)")
class LeituraPdf(unittest.TestCase):
    def test_extrai_paginas(self):
        pags = documentos.extrair_paginas(pdf_com_texto(["R.3 HIPOTECA em favor do banco", "Imovel ocupado"]))
        self.assertEqual(len(pags), 2)
        self.assertIn("HIPOTECA", pags[0])

    def test_ficha_mostra_trechos_por_item(self):
        con = base_teste(); self.addCleanup(con.close)
        iid = con.con.execute("SELECT id FROM imoveis LIMIT 1").fetchone()[0]
        pasta = tempfile.mkdtemp()
        r = ficha.anexar(con, pasta, iid, "edital", "edital.pdf",
                         pdf_com_texto(["O imovel encontra-se ocupado.", "Debitos de condominio por conta do adquirente."]))
        self.assertEqual(r["anexos"][0]["leitura"], "lido")
        self.assertEqual(set(r["achados"]), {"ocupacao", "condominio", "edital"})
        oc = r["achados"]["ocupacao"][0]
        self.assertEqual((oc["pagina"], oc["documento"], oc["achado"]), (1, "edital.pdf", "ocupado"))
        self.assertIn("ocupacao", ficha.ficha(con, iid)["achados"])

    def test_pdf_sem_texto(self):
        con = base_teste(); self.addCleanup(con.close)
        iid = con.con.execute("SELECT id FROM imoveis LIMIT 1").fetchone()[0]
        r = ficha.anexar(con, tempfile.mkdtemp(), iid, "matricula", "scan.pdf", pdf_com_texto([""]))
        self.assertEqual(r["anexos"][0]["leitura"], "sem_texto")
        self.assertEqual(r["achados"], {})


class SemPypdf(unittest.TestCase):
    def test_anexo_funciona_com_leitura_desligada(self):
        original = documentos.pypdf
        documentos.pypdf = None
        try:
            con = base_teste(); self.addCleanup(con.close)
            iid = con.con.execute("SELECT id FROM imoveis LIMIT 1").fetchone()[0]
            r = ficha.anexar(con, tempfile.mkdtemp(), iid, "edital", "e.pdf", pdf_com_texto(["ocupado"]))
            self.assertEqual(r["anexos"][0]["leitura"], "desligada")
            self.assertFalse(ficha.ficha(con, iid)["leitura_pdf"])
        finally:
            documentos.pypdf = original


if __name__ == "__main__":
    unittest.main()
