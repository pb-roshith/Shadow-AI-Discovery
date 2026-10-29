from io import BytesIO
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_repo_apps import load

module = load('credit-dossier')


class CreditMemo(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(module.app)

    def upload(self, name, content):
        return self.client.post('/api/memo', files={'file': (name, content)})

    def test_text_upload_then_grounded_question(self):
        with patch.object(module, 'summarise', return_value='Debt is 42 [Paragraph 2].') as model:
            uploaded = self.upload('credit.txt', b'Borrower: Acme\nDebt: 42')
            self.assertEqual(uploaded.status_code, 200)
            model.assert_not_called()
            memo = uploaded.json()
            self.assertEqual(memo['sections'], 2)
            self.assertIn('[Paragraph 2]\nDebt: 42', memo['text'])
            response = self.client.post('/api/run', json={'memo': memo['text'], 'text': 'What is the debt?', 'provider': 'gemini'})
            self.assertEqual(response.status_code, 200)
            prompt = model.call_args.args[0]
            self.assertIn('Debt: 42', prompt)
            self.assertIn('What is the debt?', prompt)
            self.assertIn('does not provide this information', prompt)
            self.assertIn('Never invent a citation', prompt)
            self.assertEqual(model.call_args.kwargs['request_id'], response.headers['x-request-id'])

    def test_no_memo_no_ai_invocation(self):
        with patch.object(module, 'summarise') as model:
            for body in ({'text': 'Hello'}, {'text': 'Hello', 'memo': '   '}, {'text': ' ', 'memo': 'Borrower'}):
                self.assertEqual(self.client.post('/api/run', json=body).status_code, 422)
            model.assert_not_called()

    def test_reject_invalid_empty_and_oversized_documents(self):
        for name, content in [('memo.exe', b'content'), ('memo.txt', b''), ('memo.pdf', b'broken'),
                              ('memo.txt', b'\xff'), ('memo.docx', b'broken'),
                              ('memo.txt', b'x' * (120001)), ('memo.txt', b'x' * (5 * 1024 * 1024 + 1))]:
            with self.subTest(name=name, size=len(content)):
                self.assertEqual(self.upload(name, content).status_code, 422)

    def test_word_paragraphs_and_tables_have_source_labels(self):
        from docx import Document
        document = Document()
        document.add_paragraph('Borrower: Acme')
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = 'Collateral'
        table.cell(0, 1).text = 'Property'
        data = BytesIO()
        document.save(data)
        response = self.upload('memo.docx', data.getvalue())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['sections'], 3)
        self.assertIn('[Paragraph 3]\nProperty', response.json()['text'])

    def test_pdf_text_has_page_reference_and_scans_are_rejected(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 72 720 Td (Borrower Acme) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        data = BytesIO()
        writer.write(data)
        response = self.upload('memo.pdf', data.getvalue())
        self.assertEqual(response.status_code, 200)
        self.assertIn('[Page 1]\nBorrower Acme', response.json()['text'])
        blank = PdfWriter()
        blank.add_blank_page(width=100, height=100)
        data = BytesIO()
        blank.write(data)
        self.assertEqual(self.upload('scan.pdf', data.getvalue()).status_code, 422)
