"""
LLM Pricing utility for cost calculation and tracking.
Provides real-time cost calculations based on token usage.
"""

import json
import os
from typing import Dict, Optional, Tuple
from datetime import datetime

class LLMPricing:
    def __init__(self):
        self.pricing_data = None
        self.pricing_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'llmPricing.json')
        self.load_pricing_data()
    
    def load_pricing_data(self) -> None:
        """Load pricing data from JSON file"""
        try:
            with open(self.pricing_file, 'r', encoding='utf-8') as f:
                self.pricing_data = json.load(f)
        except FileNotFoundError:
            print(f"Warning: Pricing file not found at {self.pricing_file}")
            self.pricing_data = {"pricing": {}}
        except json.JSONDecodeError:
            print(f"Warning: Invalid JSON in pricing file {self.pricing_file}")
            self.pricing_data = {"pricing": {}}
    
    def get_model_pricing(self, model: str) -> Optional[Dict[str, float]]:
        """Get pricing information for a specific model"""
        if not self.pricing_data:
            return None
        
        # Determine provider based on model name
        if model.startswith("gemini"):
            provider = "gemini"
        elif model.startswith("mercury"):
            provider = "inception"
        else:
            return None
        
        pricing = self.pricing_data.get("pricing", {}).get(provider, {})
        return pricing.get(model)
    
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int, image_count: int = 0) -> Tuple[float, Dict[str, float]]:
        """
        Calculate the cost for a given model and token usage.
        
        Args:
            model: The model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            
        Returns:
            Tuple of (total_cost, cost_breakdown)
        """
        pricing = self.get_model_pricing(model)
        if not pricing:
            return 0.0, {"input_cost": 0.0, "output_cost": 0.0, "total_cost": 0.0, "error": "No pricing data available"}
        
        # Convert tokens to millions for calculation
        input_millions = input_tokens / 1_000_000
        output_millions = output_tokens / 1_000_000
        
        # Calculate token-based costs
        input_cost = input_millions * pricing["input_per_million"]
        output_cost = output_millions * pricing["output_per_million"]
        
        # Optional image-based cost (for models like Gemini 2.5 Flash that bill per image)
        image_cost = 0.0
        image_price = pricing.get("image_input_per_image")
        if image_price and image_count > 0:
            image_cost = image_count * image_price
        
        total_cost = input_cost + output_cost + image_cost
        
        cost_breakdown = {
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "image_cost": round(image_cost, 6),
            "total_cost": round(total_cost, 6),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "image_count": image_count,
            "model": model,
            "pricing_per_million": pricing
        }
        
        return round(total_cost, 6), cost_breakdown
    
    def get_all_supported_models(self) -> Dict[str, Dict[str, float]]:
        """Get pricing for all supported models"""
        if not self.pricing_data:
            return {}
        
        all_models = {}
        for provider, models in self.pricing_data.get("pricing", {}).items():
            all_models.update(models)
        
        return all_models
    
    def format_cost(self, cost: float, _currency: str = "USD") -> str:
        """Format cost for display"""
        if cost == 0.0:
            return "$0.00000"
        else:
            return f"${cost:.5f}"
    
    def get_pricing_metadata(self) -> Dict:
        """Get metadata about pricing data"""
        if not self.pricing_data:
            return {}
        return self.pricing_data.get("metadata", {})
    
    def is_pricing_current(self, days_threshold: int = 30) -> bool:
        """Check if pricing data is current (within threshold days)"""
        metadata = self.get_pricing_metadata()
        last_updated = metadata.get("last_updated")
        
        if not last_updated:
            return False
        
        try:
            updated_date = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
            days_old = (datetime.now().astimezone() - updated_date).days
            return days_old <= days_threshold
        except (TypeError, ValueError, AttributeError):
            return False

# Global pricing instance
llm_pricing = LLMPricing()
