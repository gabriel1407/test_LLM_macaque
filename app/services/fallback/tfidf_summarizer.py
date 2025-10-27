"""
TF-IDF-based fallback summarization service.
Implements extractive summarization using Term Frequency-Inverse Document Frequency.
"""
import time
import re
from typing import List, Dict, Any
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from collections import Counter
import nltk
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.corpus import stopwords

from app.core.logging import LoggerMixin, log_performance
from app.core.exceptions import FallbackError, TextProcessingError
from app.domain.interfaces.fallback_service import TFIDFFallbackService, FallbackAlgorithm
from app.domain.entities.summary_request import SummaryRequest, LanguageCode
from app.domain.entities.summary_response import SummaryResponse, TokenUsage, SummarySource


class TFIDFSummarizer(TFIDFFallbackService, LoggerMixin):
    """
    TF-IDF-based extractive summarization service.
    
    Uses term frequency and inverse document frequency to rank sentences.
    """
    
    def __init__(self, min_sentence_length: int = 10):
        """
        Initialize TF-IDF summarizer.
        
        Args:
            min_sentence_length: Minimum character length for sentences
        """
        self.min_sentence_length = min_sentence_length
        
        # Download required NLTK data
        self._ensure_nltk_data()
        
        self.logger.info("TF-IDF summarizer initialized")
    
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
        """Generate extractive summary using TF-IDF."""
        start_time = time.time()
        
        try:
            self.logger.info(f"Generating TF-IDF summary: {request}")
            
            # Extract sentences using TF-IDF
            sentences = await self.extract_sentences(
                request.text,
                self._calculate_num_sentences(request),
                self.min_sentence_length
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
                model="tfidf",
                latency_ms=latency_ms,
                source=SummarySource.FALLBACK_TFIDF,
                request_id=request.request_id
            )
            
            # Log performance
            log_performance(
                operation="tfidf_summary_generation",
                latency_ms=latency_ms,
                sentences_extracted=len(sentences),
                compression_ratio=len(summary_text) / len(request.text)
            )
            
            self.logger.info(f"TF-IDF summary generated: {response}")
            return response
            
        except Exception as e:
            self.logger.error(f"TF-IDF summarization failed: {e}")
            raise FallbackError(f"TF-IDF summarization failed: {e}")
    
    async def extract_sentences(
        self, 
        text: str, 
        num_sentences: int,
        min_sentence_length: int = None
    ) -> List[str]:
        """Extract the most important sentences using TF-IDF."""
        try:
            min_length = min_sentence_length or self.min_sentence_length
            
            # Tokenize into sentences
            sentences = sent_tokenize(text)
            
            # Filter sentences by length
            valid_sentences = [
                s for s in sentences 
                if len(s.strip()) >= min_length
            ]
            
            if len(valid_sentences) <= num_sentences:
                return valid_sentences
            
            # Calculate TF-IDF scores for sentences
            scores = await self.get_sentence_scores(text)
            
            # Sort sentences by score and get top ones
            scored_sentences = [
                (s, scores.get(s, 0.0)) for s in valid_sentences
            ]
            scored_sentences.sort(key=lambda x: x[1], reverse=True)
            
            # Get top sentences
            top_sentences = [s[0] for s in scored_sentences[:num_sentences]]
            
            # Return sentences in original order
            original_order = []
            for sentence in sentences:
                if sentence in top_sentences:
                    original_order.append(sentence)
            
            return original_order
            
        except Exception as e:
            raise TextProcessingError(f"Sentence extraction failed: {e}")
    
    async def get_sentence_scores(self, text: str) -> Dict[str, float]:
        """Get TF-IDF scores for all sentences."""
        try:
            sentences = sent_tokenize(text)
            
            if len(sentences) <= 1:
                return {sentences[0]: 1.0} if sentences else {}
            
            # Preprocess sentences
            processed_sentences = [self._preprocess_sentence(s) for s in sentences]
            
            # Calculate TF-IDF
            vectorizer = TfidfVectorizer(
                stop_words='english',
                lowercase=True,
                max_features=1000,
                ngram_range=(1, 2)  # Include bigrams
            )
            
            tfidf_matrix = vectorizer.fit_transform(processed_sentences)
            
            # Calculate sentence scores (sum of TF-IDF values)
            sentence_scores = np.array(tfidf_matrix.sum(axis=1)).flatten()
            
            # Normalize scores
            if sentence_scores.max() > 0:
                sentence_scores = sentence_scores / sentence_scores.max()
            
            return {sentences[i]: float(sentence_scores[i]) for i in range(len(sentences))}
            
        except Exception as e:
            raise TextProcessingError(f"Score calculation failed: {e}")
    
    async def get_keyword_scores(self, text: str, top_k: int = 10) -> Dict[str, float]:
        """Get top keywords with their TF-IDF scores."""
        try:
            # Preprocess text
            processed_text = self._preprocess_sentence(text)
            
            # Calculate TF-IDF for words
            vectorizer = TfidfVectorizer(
                stop_words='english',
                lowercase=True,
                max_features=top_k * 2,  # Get more features to filter later
                ngram_range=(1, 2)
            )
            
            tfidf_matrix = vectorizer.fit_transform([processed_text])
            feature_names = vectorizer.get_feature_names_out()
            
            # Get scores
            scores = tfidf_matrix.toarray()[0]
            
            # Create keyword-score pairs
            keyword_scores = list(zip(feature_names, scores))
            keyword_scores.sort(key=lambda x: x[1], reverse=True)
            
            return dict(keyword_scores[:top_k])
            
        except Exception as e:
            raise TextProcessingError(f"Keyword extraction failed: {e}")
    
    def _preprocess_sentence(self, sentence: str) -> str:
        """Preprocess sentence for TF-IDF calculation."""
        # Remove special characters but keep some punctuation
        sentence = re.sub(r'[^\w\s\.\,\!\?]', '', sentence)
        
        # Convert to lowercase
        sentence = sentence.lower()
        
        # Remove extra whitespace
        sentence = ' '.join(sentence.split())
        
        return sentence
    
    def _calculate_num_sentences(self, request: SummaryRequest) -> int:
        """Calculate optimal number of sentences for the summary."""
        # Estimate based on max_tokens and average sentence length
        avg_tokens_per_sentence = 20  # Rough estimate
        max_sentences = max(1, request.max_tokens // avg_tokens_per_sentence)
        
        # Also consider original text length
        total_sentences = len(sent_tokenize(request.text))
        
        # Use 15-25% of original sentences, but respect token limit
        suggested_sentences = max(1, min(max_sentences, total_sentences // 4))
        
        return min(suggested_sentences, 8)  # Cap at 8 sentences
    
    def get_algorithm_name(self) -> FallbackAlgorithm:
        """Get algorithm name."""
        return FallbackAlgorithm.TFIDF
    
    def supports_language(self, language_code: str) -> bool:
        """Check if language is supported."""
        # TF-IDF works well with most languages
        supported_languages = {
            LanguageCode.AUTO, LanguageCode.ENGLISH, LanguageCode.SPANISH,
            LanguageCode.FRENCH, LanguageCode.GERMAN, LanguageCode.ITALIAN,
            LanguageCode.PORTUGUESE, LanguageCode.RUSSIAN
        }
        
        try:
            lang_enum = LanguageCode(language_code)
            return lang_enum in supported_languages
        except ValueError:
            return False
    
    async def health_check(self) -> Dict[str, Any]:
        """Check TF-IDF service health."""
        try:
            # Test with a simple text
            test_text = """
            This is a test document for TF-IDF analysis. 
            It contains multiple sentences with different terms.
            The algorithm should be able to identify important sentences.
            This helps ensure the service is working correctly.
            """
            
            sentences = await self.extract_sentences(test_text.strip(), 2)
            keywords = await self.get_keyword_scores(test_text.strip(), 5)
            
            return {
                "status": "healthy",
                "algorithm": "tfidf",
                "test_result": {
                    "sentences_extracted": len(sentences),
                    "keywords_found": len(keywords)
                }
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "algorithm": "tfidf",
                "error": str(e)
            }
