"""
TextRank-based fallback summarization service.
Implements extractive summarization using the TextRank algorithm.
"""
import time
import re
from typing import List, Dict, Any
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import nltk
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer

from app.core.logging import LoggerMixin, log_performance
from app.core.exceptions import FallbackError, TextProcessingError
from app.domain.interfaces.fallback_service import TextRankFallbackService, FallbackAlgorithm
from app.domain.entities.summary_request import SummaryRequest, LanguageCode
from app.domain.entities.summary_response import SummaryResponse, TokenUsage, SummarySource


class TextRankSummarizer(TextRankFallbackService, LoggerMixin):
    """
    TextRank-based extractive summarization service.
    
    Uses graph-based ranking to identify the most important sentences.
    """
    
    def __init__(self, similarity_threshold: float = 0.1, damping_factor: float = 0.85):
        """
        Initialize TextRank summarizer.
        
        Args:
            similarity_threshold: Minimum similarity for sentence connections
            damping_factor: Damping factor for PageRank algorithm
        """
        self.similarity_threshold = similarity_threshold
        self.damping_factor = damping_factor
        self.stemmer = PorterStemmer()
        
        # Download required NLTK data
        self._ensure_nltk_data()
        
        # Language-specific stopwords
        self.stopwords_cache = {}
        
        self.logger.info("TextRank summarizer initialized")
    
    def _ensure_nltk_data(self):
        """Ensure required NLTK data is downloaded."""
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            nltk.download('punkt', quiet=True)
        
        try:
            nltk.data.find('corpora/stopwords')
        except LookupError:
            nltk.download('stopwords', quiet=True)
    
    async def generate_summary(self, request: SummaryRequest) -> SummaryResponse:
        """Generate extractive summary using TextRank."""
        start_time = time.time()
        
        try:
            self.logger.info(f"Generating TextRank summary: {request}")
            
            # Extract sentences using TextRank
            sentences = await self.extract_sentences(
                request.text,
                self._calculate_num_sentences(request)
            )
            
            # Join sentences to form summary
            summary_text = ' '.join(sentences)
            
            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            
            # Estimate token usage
            prompt_tokens = len(request.text) // 4
            completion_tokens = len(summary_text) // 4
            
            response = SummaryResponse(
                summary=summary_text,
                usage=TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens
                ),
                model="textrank",
                latency_ms=latency_ms,
                source=SummarySource.FALLBACK_TEXTRANK,
                request_id=request.request_id
            )
            
            # Log performance
            log_performance(
                operation="textrank_summary_generation",
                latency_ms=latency_ms,
                sentences_extracted=len(sentences),
                compression_ratio=len(summary_text) / len(request.text)
            )
            
            self.logger.info(f"TextRank summary generated: {response}")
            return response
            
        except Exception as e:
            self.logger.error(f"TextRank summarization failed: {e}")
            raise FallbackError(f"TextRank summarization failed: {e}")
    
    async def extract_sentences(
        self, 
        text: str, 
        num_sentences: int,
        similarity_threshold: float = None
    ) -> List[str]:
        """Extract the most important sentences using TextRank."""
        try:
            threshold = similarity_threshold or self.similarity_threshold
            
            # Tokenize into sentences
            sentences = sent_tokenize(text)
            
            if len(sentences) <= num_sentences:
                return sentences
            
            # Preprocess sentences
            processed_sentences = [self._preprocess_sentence(s) for s in sentences]
            
            # Create TF-IDF vectors
            vectorizer = TfidfVectorizer(stop_words='english', lowercase=True)
            tfidf_matrix = vectorizer.fit_transform(processed_sentences)
            
            # Calculate similarity matrix
            similarity_matrix = cosine_similarity(tfidf_matrix)
            
            # Apply threshold
            similarity_matrix[similarity_matrix < threshold] = 0
            
            # Apply TextRank (PageRank) algorithm
            scores = self._textrank_algorithm(similarity_matrix)
            
            # Get top sentences
            ranked_indices = np.argsort(scores)[::-1][:num_sentences]
            
            # Return sentences in original order
            ranked_indices = sorted(ranked_indices)
            return [sentences[i] for i in ranked_indices]
            
        except Exception as e:
            raise TextProcessingError(f"Sentence extraction failed: {e}")
    
    async def get_sentence_scores(self, text: str) -> Dict[str, float]:
        """Get TextRank scores for all sentences."""
        try:
            sentences = sent_tokenize(text)
            processed_sentences = [self._preprocess_sentence(s) for s in sentences]
            
            vectorizer = TfidfVectorizer(stop_words='english', lowercase=True)
            tfidf_matrix = vectorizer.fit_transform(processed_sentences)
            similarity_matrix = cosine_similarity(tfidf_matrix)
            similarity_matrix[similarity_matrix < self.similarity_threshold] = 0
            
            scores = self._textrank_algorithm(similarity_matrix)
            
            return {sentences[i]: float(scores[i]) for i in range(len(sentences))}
            
        except Exception as e:
            raise TextProcessingError(f"Score calculation failed: {e}")
    
    def _textrank_algorithm(self, similarity_matrix: np.ndarray, max_iterations: int = 100) -> np.ndarray:
        """Apply TextRank (PageRank) algorithm."""
        n = similarity_matrix.shape[0]
        
        # Normalize similarity matrix
        row_sums = similarity_matrix.sum(axis=1)
        # Avoid division by zero
        row_sums[row_sums == 0] = 1
        normalized_matrix = similarity_matrix / row_sums[:, np.newaxis]
        
        # Initialize scores
        scores = np.ones(n) / n
        
        # Iterate until convergence
        for _ in range(max_iterations):
            new_scores = (1 - self.damping_factor) / n + self.damping_factor * normalized_matrix.T.dot(scores)
            
            # Check for convergence
            if np.allclose(scores, new_scores, atol=1e-6):
                break
                
            scores = new_scores
        
        return scores
    
    def _preprocess_sentence(self, sentence: str) -> str:
        """Preprocess sentence for similarity calculation."""
        # Remove special characters and digits
        sentence = re.sub(r'[^a-zA-Z\s]', '', sentence)
        
        # Tokenize and stem
        words = word_tokenize(sentence.lower())
        
        # Remove stopwords
        stop_words = set(stopwords.words('english'))
        words = [self.stemmer.stem(word) for word in words if word not in stop_words]
        
        return ' '.join(words)
    
    def _calculate_num_sentences(self, request: SummaryRequest) -> int:
        """Calculate optimal number of sentences for the summary."""
        # Estimate based on max_tokens and average sentence length
        avg_tokens_per_sentence = 20  # Rough estimate
        max_sentences = max(1, request.max_tokens // avg_tokens_per_sentence)
        
        # Also consider original text length
        total_sentences = len(sent_tokenize(request.text))
        
        # Use 20-30% of original sentences, but respect token limit
        suggested_sentences = max(1, min(max_sentences, total_sentences // 3))
        
        return min(suggested_sentences, 10)  # Cap at 10 sentences
    
    def get_algorithm_name(self) -> FallbackAlgorithm:
        """Get algorithm name."""
        return FallbackAlgorithm.TEXTRANK
    
    def supports_language(self, language_code: str) -> bool:
        """Check if language is supported."""
        # TextRank works with most languages, but we have better support for some
        supported_languages = {
            LanguageCode.AUTO, LanguageCode.ENGLISH, LanguageCode.SPANISH,
            LanguageCode.FRENCH, LanguageCode.GERMAN, LanguageCode.ITALIAN,
            LanguageCode.PORTUGUESE
        }
        
        try:
            lang_enum = LanguageCode(language_code)
            return lang_enum in supported_languages
        except ValueError:
            return False
    
    async def health_check(self) -> Dict[str, Any]:
        """Check TextRank service health."""
        try:
            # Test with a simple text
            test_text = "This is a test sentence. This is another test sentence for validation."
            sentences = await self.extract_sentences(test_text, 1)
            
            return {
                "status": "healthy",
                "algorithm": "textrank",
                "test_result": len(sentences) > 0
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "algorithm": "textrank",
                "error": str(e)
            }
