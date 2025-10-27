"""
Interface for fallback summarization services.
Provides extractive summarization when LLM providers fail.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from enum import Enum

from app.domain.entities.summary_request import SummaryRequest
from app.domain.entities.summary_response import SummaryResponse


class FallbackAlgorithm(str, Enum):
    """Available fallback algorithms for extractive summarization."""
    TEXTRANK = "textrank"
    TFIDF = "tfidf"
    FREQUENCY = "frequency"
    LUHN = "luhn"
    LSA = "lsa"  # Latent Semantic Analysis


class FallbackService(ABC):
    """
    Abstract base class for fallback summarization services.
    
    Provides extractive summarization when LLM providers are unavailable
    or fail to generate summaries.
    """
    
    @abstractmethod
    async def generate_summary(self, request: SummaryRequest) -> SummaryResponse:
        """
        Generate an extractive summary for the given request.
        
        Args:
            request: The summary request containing text and parameters
            
        Returns:
            SummaryResponse: The generated extractive summary
            
        Raises:
            FallbackError: If fallback summarization fails
        """
        pass
    
    @abstractmethod
    def get_algorithm_name(self) -> FallbackAlgorithm:
        """
        Get the name of the fallback algorithm.
        
        Returns:
            FallbackAlgorithm: The algorithm used by this service
        """
        pass
    
    @abstractmethod
    def supports_language(self, language_code: str) -> bool:
        """
        Check if the fallback service supports the given language.
        
        Args:
            language_code: Language code to check (e.g., "en", "es")
            
        Returns:
            bool: True if language is supported
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the fallback service.
        
        Returns:
            Dict containing health status information
        """
        pass


class TextRankFallbackService(FallbackService):
    """
    Interface for TextRank-based fallback summarization.
    
    TextRank is a graph-based ranking algorithm for extractive summarization.
    """
    
    @abstractmethod
    async def extract_sentences(
        self, 
        text: str, 
        num_sentences: int,
        similarity_threshold: float = 0.1
    ) -> List[str]:
        """
        Extract the most important sentences using TextRank.
        
        Args:
            text: Input text to summarize
            num_sentences: Number of sentences to extract
            similarity_threshold: Minimum similarity for sentence connections
            
        Returns:
            List of extracted sentences
        """
        pass
    
    @abstractmethod
    async def get_sentence_scores(self, text: str) -> Dict[str, float]:
        """
        Get TextRank scores for all sentences.
        
        Args:
            text: Input text to analyze
            
        Returns:
            Dict mapping sentences to their TextRank scores
        """
        pass


class TFIDFFallbackService(FallbackService):
    """
    Interface for TF-IDF-based fallback summarization.
    
    Uses Term Frequency-Inverse Document Frequency for sentence ranking.
    """
    
    @abstractmethod
    async def extract_sentences(
        self, 
        text: str, 
        num_sentences: int,
        min_sentence_length: int = 10
    ) -> List[str]:
        """
        Extract the most important sentences using TF-IDF.
        
        Args:
            text: Input text to summarize
            num_sentences: Number of sentences to extract
            min_sentence_length: Minimum character length for sentences
            
        Returns:
            List of extracted sentences
        """
        pass
    
    @abstractmethod
    async def get_sentence_scores(self, text: str) -> Dict[str, float]:
        """
        Get TF-IDF scores for all sentences.
        
        Args:
            text: Input text to analyze
            
        Returns:
            Dict mapping sentences to their TF-IDF scores
        """
        pass
    
    @abstractmethod
    async def get_keyword_scores(self, text: str, top_k: int = 10) -> Dict[str, float]:
        """
        Get top keywords with their TF-IDF scores.
        
        Args:
            text: Input text to analyze
            top_k: Number of top keywords to return
            
        Returns:
            Dict mapping keywords to their TF-IDF scores
        """
        pass


class FallbackServiceFactory(ABC):
    """
    Factory interface for creating fallback services.
    
    Follows the Factory pattern and Dependency Inversion Principle.
    """
    
    @abstractmethod
    def create_service(self, algorithm: FallbackAlgorithm, **kwargs) -> FallbackService:
        """
        Create a fallback service instance.
        
        Args:
            algorithm: Type of fallback algorithm to use
            **kwargs: Additional configuration parameters
            
        Returns:
            FallbackService: Configured fallback service instance
            
        Raises:
            ConfigurationError: If algorithm is unsupported or configuration is invalid
        """
        pass
    
    @abstractmethod
    def get_supported_algorithms(self) -> List[FallbackAlgorithm]:
        """
        Get list of supported fallback algorithms.
        
        Returns:
            List of supported algorithm types
        """
        pass


class FallbackServiceSelector(ABC):
    """
    Interface for selecting the best fallback service based on context.
    
    Implements strategy pattern for fallback service selection.
    """
    
    @abstractmethod
    async def select_service(
        self, 
        request: SummaryRequest,
        available_services: List[FallbackService]
    ) -> FallbackService:
        """
        Select the best fallback service for the given request.
        
        Args:
            request: The summary request
            available_services: List of available fallback services
            
        Returns:
            FallbackService: The selected service
            
        Raises:
            FallbackError: If no suitable service is available
        """
        pass
    
    @abstractmethod
    def get_selection_criteria(self) -> Dict[str, Any]:
        """
        Get the criteria used for service selection.
        
        Returns:
            Dict describing selection criteria
        """
        pass


class FallbackServiceWithQuality(FallbackService):
    """
    Extended fallback interface with quality assessment.
    
    Follows ISP by separating quality assessment into a separate interface.
    """
    
    @abstractmethod
    async def assess_quality(
        self, 
        original_text: str, 
        summary: str
    ) -> Dict[str, float]:
        """
        Assess the quality of a generated summary.
        
        Args:
            original_text: Original text that was summarized
            summary: Generated summary
            
        Returns:
            Dict containing quality metrics (e.g., coverage, coherence)
        """
        pass
    
    @abstractmethod
    async def get_confidence_score(
        self, 
        request: SummaryRequest
    ) -> float:
        """
        Get confidence score for summarizing the given request.
        
        Args:
            request: Summary request to assess
            
        Returns:
            float: Confidence score between 0 and 1
        """
        pass
