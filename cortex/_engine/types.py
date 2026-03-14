from dataclasses import dataclass, field

@dataclass
class TokenCount:
    """Represents split tracking of input and output tokens."""
    input: int = 0
    output: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output

    def add(self, token_info: dict):
        """Safely increments counts from an LLM token_info dictionary."""
        if not token_info:
            return
        self.input += token_info.get("input_tokens", 0)
        self.output += token_info.get("output_tokens", 0)
        
    def __str__(self) -> str:
        return f"{self.total} (in: {self.input}, out: {self.output})"

@dataclass
class TokenUsage:
    """Tracks token consumption across different agent lifecycle phases."""
    task: TokenCount = field(default_factory=TokenCount)
    summarizer: TokenCount = field(default_factory=TokenCount)
    extractor: TokenCount = field(default_factory=TokenCount)
    
    @property
    def total(self) -> int:
        return self.task.total + self.summarizer.total + self.extractor.total
