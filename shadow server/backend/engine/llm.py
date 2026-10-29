"""Shared SDK adapter; credentials remain in the backend."""
import importlib.util
from engine.config import ROOT


def complete(message):
    path = ROOT.parents[1] / 'repo server/credit-dossier/dossier/llm.py'
    spec = importlib.util.spec_from_file_location('shared_llm', path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    return adapter.summarise(message, app_id='shadow-discovery')
