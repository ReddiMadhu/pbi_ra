import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Toggle to enable or disable LLM caching to save API costs during testing
USE_LLM_CACHE = True

def get_llm(temperature=0.1):
    """
    Returns an instance of ChatOpenAI or AzureChatOpenAI based on the configured environment variables.
    Returns None if no API key is configured.
    """
    llm = None
    
    openai_api_key = os.getenv("OPENAI_API_KEY")
    azure_api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if azure_api_key:
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        
        # Handle Azure AI Foundry Serverless/MaaS Endpoints
        if azure_endpoint and ("services.ai.azure.com" in azure_endpoint or "models.ai.azure.com" in azure_endpoint):
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                api_key=azure_api_key,
                base_url=azure_endpoint,
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-2"),
                temperature=temperature,
                default_headers={"api-key": azure_api_key}
            )
            
        else:
            # Handle Standard Azure OpenAI Endpoints
            from langchain_openai import AzureChatOpenAI
            llm = AzureChatOpenAI(
                api_key=azure_api_key,
                azure_endpoint=azure_endpoint,
                azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini-2"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                temperature=temperature
            )
    elif openai_api_key:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            api_key=openai_api_key,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini-2"),
            temperature=temperature
        )
    
    if llm and USE_LLM_CACHE:
        from app.core.cache import CachedLLM
        return CachedLLM(llm)
        
    return llm
