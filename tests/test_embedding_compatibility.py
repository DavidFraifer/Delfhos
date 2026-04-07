"""
Test embedding model compatibility and auto-detection.

Verifies that the EmbeddingModelInfo class can handle any sentence-transformers model
and correctly auto-detect their requirements.
"""

import pytest
from delfhos.memory.persistent import EmbeddingModelInfo


class TestEmbeddingModelDetection:
    """Test auto-detection of model requirements."""
    
    def test_requires_trust_remote_code_nomic(self):
        """Nomic models require trust_remote_code."""
        assert EmbeddingModelInfo.requires_trust_remote_code("nomic-embed-text")
        assert EmbeddingModelInfo.requires_trust_remote_code("nomic-ai/nomic-embed-text")
        assert EmbeddingModelInfo.requires_trust_remote_code("nomic-ai/nomic-embed-text-v1.5")
        assert EmbeddingModelInfo.requires_trust_remote_code("NOMIC-EMBED-TEXT")  # case-insensitive
    
    def test_requires_trust_remote_code_bge(self):
        """BGE models require trust_remote_code."""
        assert EmbeddingModelInfo.requires_trust_remote_code("bge-base-en")
        assert EmbeddingModelInfo.requires_trust_remote_code("bge-small-en-v1.5")
        assert EmbeddingModelInfo.requires_trust_remote_code("BAAI/bge-base-en-v1.5")
    
    def test_requires_trust_remote_code_jina(self):
        """Jina models require trust_remote_code."""
        assert EmbeddingModelInfo.requires_trust_remote_code("jina-embedding-t-en-v1")
        assert EmbeddingModelInfo.requires_trust_remote_code("jinaai/jina-embedding-t-en-v1")
    
    def test_does_not_require_trust_remote_standard_models(self):
        """Standard models don't require trust_remote_code."""
        assert not EmbeddingModelInfo.requires_trust_remote_code("all-MiniLM-L6-v2")
        assert not EmbeddingModelInfo.requires_trust_remote_code("all-mpnet-base-v2")
        assert not EmbeddingModelInfo.requires_trust_remote_code("paraphrase-MPNET-base-v2")
        assert not EmbeddingModelInfo.requires_trust_remote_code("sentence-transformers/all-MiniLM-L6-v2")
    
    def test_get_prefixes_nomic(self):
        """Nomic models have search_document/search_query prefixes."""
        assert EmbeddingModelInfo.get_prefixes("nomic-embed-text") == ("search_document: ", "search_query: ")
        assert EmbeddingModelInfo.get_prefixes("nomic-ai/nomic-embed-text-v1.5") == ("search_document: ", "search_query: ")
        assert EmbeddingModelInfo.get_prefixes("nomic-ai/nomic-embed-text-v1") == ("search_document: ", "search_query: ")
    
    def test_get_prefixes_standard_models(self):
        """Standard models don't have special prefixes."""
        assert EmbeddingModelInfo.get_prefixes("all-MiniLM-L6-v2") is None
        assert EmbeddingModelInfo.get_prefixes("all-mpnet-base-v2") is None
        assert EmbeddingModelInfo.get_prefixes("sentence-transformers/all-MiniLM-L6-v2") is None
    
    def test_normalize_model_name_with_aliases(self):
        """Model names with aliases are resolved."""
        aliases = {
            "all-MiniLM-L6-v2": "all-MiniLM-L6-v2",
            "nomic-embed-text": "nomic-ai/nomic-embed-text-v1.5",
        }
        
        assert EmbeddingModelInfo.normalize_model_name("all-MiniLM-L6-v2", aliases) == "all-MiniLM-L6-v2"
        assert EmbeddingModelInfo.normalize_model_name("nomic-embed-text", aliases) == "nomic-ai/nomic-embed-text-v1.5"
    
    def test_normalize_model_name_without_aliases(self):
        """Model names without aliases pass through unchanged."""
        aliases = {
            "all-MiniLM-L6-v2": "all-MiniLM-L6-v2",
        }
        
        # Unknown model should pass through
        assert EmbeddingModelInfo.normalize_model_name("sentence-transformers/all-mpnet-base-v2", aliases) == "sentence-transformers/all-mpnet-base-v2"
        assert EmbeddingModelInfo.normalize_model_name("BAAI/bge-base-en-v1.5", aliases) == "BAAI/bge-base-en-v1.5"


class TestMemoryEmbeddingCompatibility:
    """Test Memory class with various model types (without importing real models)."""
    
    def test_memory_default_model(self):
        """Memory uses default model if not specified."""
        from delfhos.memory.persistent import Memory
        memory = Memory()
        assert memory.embedding_model_name == "all-MiniLM-L6-v2"
    
    def test_memory_custom_model(self):
        """Memory accepts any model name."""
        from delfhos.memory.persistent import Memory
        models_to_test = [
            "all-mpnet-base-v2",
            "nomic-ai/nomic-embed-text-v1.5",
            "BAAI/bge-base-en-v1.5",
            "jinaai/jina-embedding-t-en-v1",
            "sentence-transformers/all-MiniLM-L6-v2",
        ]
        
        for model_name in models_to_test:
            memory = Memory(embedding_model=model_name)
            assert memory.embedding_model_name == model_name
    
    def test_memory_with_alias(self):
        """Memory resolves aliases."""
        from delfhos.memory.persistent import Memory
        memory = Memory(embedding_model="nomic-embed-text")
        # When accessed, it should resolve to full name
        resolved = memory._resolve_embedding_model_name()
        assert resolved == "nomic-ai/nomic-embed-text-v1.5"


class TestPopularEmbeddingModels:
    """Test detection for popular sentence-transformers models."""
    
    @pytest.mark.parametrize("model_name,should_have_prefixes", [
        ("all-MiniLM-L6-v2", False),
        ("all-MiniLM-L12-v2", False),
        ("all-mpnet-base-v2", False),
        ("sentence-t5-base", False),
        ("paraphrase-MPNET-base-v2", False),
        ("nomic-ai/nomic-embed-text-v1.5", True),
        ("nomic-ai/nomic-embed-text-v1", True),
    ])
    def test_model_prefix_detection(self, model_name, should_have_prefixes):
        """Test prefix detection for a variety of models."""
        has_prefixes = EmbeddingModelInfo.get_prefixes(model_name) is not None
        assert has_prefixes == should_have_prefixes, f"Model {model_name}: expected prefixes={should_have_prefixes}, got {has_prefixes}"
    
    @pytest.mark.parametrize("model_name,should_trust_remote", [
        ("all-MiniLM-L6-v2", False),
        ("all-mpnet-base-v2", False),
        ("paraphrase-MPNET-base-v2", False),
        ("nomic-embed-text", True),
        ("nomic-ai/nomic-embed-text-v1", True),
        ("bge-base-en-v1.5", True),
        ("BAAI/bge-large-en-v1.5", True),
        ("jinaai/jina-embedding-t-en-v1", True),
    ])
    def test_trust_remote_code_detection(self, model_name, should_trust_remote):
        """Test trust_remote_code detection for a variety of models."""
        requires_trust = EmbeddingModelInfo.requires_trust_remote_code(model_name)
        assert requires_trust == should_trust_remote, f"Model {model_name}: expected trust={should_trust_remote}, got {requires_trust}"


class TestEmbeddingDimensions:
    """Test that different models can be created and initialized (low-touch integration test)."""
    
    def test_memory_initialization_no_embedding_load(self):
        """Memory initializes without loading embedding model."""
        from delfhos.memory.persistent import Memory
        
        # Should not load model until needed
        memory = Memory()
        assert memory._model is None
        assert memory._embed_dim is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
