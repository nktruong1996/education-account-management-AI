import os
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")


def is_llm_configured() -> bool:
    return all(
        value and value.strip()
        for value in [
            API_KEY,
            AZURE_ENDPOINT,
            API_VERSION,
            DEPLOYMENT_NAME,
        ]
    )


class UnconfiguredAzureOpenAI:
    @property
    def chat(self):
        raise RuntimeError(
            "Azure OpenAI is not configured. Copy .env.example to .env "
            "and provide all AZURE_OPENAI_* values."
        )


if is_llm_configured():
    client = AzureOpenAI(
        api_key=API_KEY,
        azure_endpoint=AZURE_ENDPOINT,
        api_version=API_VERSION,
    )
else:
    client = UnconfiguredAzureOpenAI()
