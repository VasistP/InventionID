"""
File upload module

"""

import os
from typing import Optional
from anthropic import Anthropic
from openai import OpenAI
from google import genai
from google.genai import types


class FileUpload:
    def __init__(self, file_path: str):
        self.file_path = file_path

        self.anthropic_api = os.getenv("ANTHROPIC_API_KEY")
        self.openai_api = os.getenv("OPENAI_API_KEY")
        self.gemini_api = os.getenv("GEMINI_API_KEY")

    def upload(self):
        if self.file_path is None:
            raise ValueError("File path must be provided")

        if self.anthropic_api:
            pass

        if self.openai_api:
            pass

        if self.gemini_api:
            pass

    def getFile(self):
        pass
