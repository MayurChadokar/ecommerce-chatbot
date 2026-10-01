"""
Lotus Electronics Terms & Conditions and Privacy Policy Search Tool
Provides accurate information about company policies, terms, and privacy guidelines.
"""

import os
import re
import json
from typing import Dict, List, Any
from langchain_core.tools import tool
from pydantic import BaseModel, Field

DEPENDENCIES_AVAILABLE = False
if os.getenv("ENABLE_POLICY_VECTOR_SEARCH", "false").lower() == "true":
    try:
        from pinecone import Pinecone
        from sentence_transformers import SentenceTransformer
        from textblob import TextBlob
        from langchain_google_genai import ChatGoogleGenerativeAI
        DEPENDENCIES_AVAILABLE = True
    except ImportError as e:
        print(f"⚠️ Missing dependencies for T&C search: {e}")

class TermsConditionsInput(BaseModel):
    """Input schema for Terms & Conditions search."""
    query: str = Field(
        description="User's question about terms, conditions, privacy policy, or company policies. "
                   "Examples: 'return policy', 'warranty terms', 'data privacy', 'refund conditions'"
    )
    max_results: int = Field(
        default=3,
        description="Maximum number of relevant policy sections to return (1-5)"
    )

class TermsConditionsSearchTool:
    """Tool for searching Lotus Electronics Terms & Conditions and Privacy Policy."""
    
    def __init__(self, use_llm_refinement=False):
        self.is_available = DEPENDENCIES_AVAILABLE
        self.index = None
        self.model = None
        self.llm = None
        self.use_llm_refinement = use_llm_refinement
        self._initialize_components()
    
    def _initialize_components(self):
        """Initialize Pinecone, embedding model, and optionally LLM for content refinement."""
        if not self.is_available:
            return
            
        try:
            # Configuration
            self.pinecone_api_key = os.getenv(
                "PINECONE_API_KEY",
                "pcsk_3G8JGb_R6CJ2jquYjF1Rvx9HKtDGhZz24hqA5vAa6stE3LQ5AHPM3Ayr2NEKFJRH4YYgBe"
            )
            self.index_name = "lotus-tc"
            
            # Initialize embedding model
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            
            # Initialize Pinecone
            pc = Pinecone(api_key=self.pinecone_api_key)
            self.index = pc.Index(self.index_name)
            
            # Initialize LLM only if refinement is enabled
            if self.use_llm_refinement:
                google_api_key = os.getenv("GOOGLE_API_KEY", "AIzaSyAvGjCSwrbYHCphNJrBI2JHOc1Ga_2SP-k")
                self.llm = ChatGoogleGenerativeAI(
                    model="gemini-3.5-flash",
                    temperature=0.1,  # Lower temperature for faster response
                    google_api_key=google_api_key
                )
                print("✅ Terms & Conditions search tool initialized with LLM refinement")
            else:
                print("✅ Terms & Conditions search tool initialized (fast mode)")
            
        except Exception as e:
            print(f"❌ Failed to initialize T&C search tool: {e}")
            self.is_available = False
    
    def clean_and_format_text(self, text: str) -> str:
        """Enhanced text cleaning and formatting for better readability."""
        # Step 1: Basic cleaning
        cleaned = re.sub(r'\s+', ' ', text).strip()
        
        # Step 2: Fix common OCR errors
        fixes = {
            'cust omer': 'customer',
            'lotuselectr onics': 'Lotus Electronics',
            'deliv ery': 'delivery',
            'ser vices': 'services',
            'transpor tation': 'transportation',
            'Howe ver': 'However',
            'effor t': 'effort',
            'conv enience': 'convenience',
            'befor e': 'before',
            'receiv e': 'receive',
            'tamper ed': 'tampered',
            'char ges': 'charges',
            'defectiv e': 'defective',
            'contr ol': 'control',
            'speci\ufb01cation': 'specification',
            'entir e': 'entire',
            'unlik ely': 'unlikely',
            'Certiﬁcate': 'Certificate',
            'wa y': 'way',
            'v e': 've',
            'Lotuselectr onics.com': 'Lotus Electronics',
            'lotuselectr onics.com': 'Lotus Electronics'
        }
        
        for old, new in fixes.items():
            cleaned = cleaned.replace(old, new)
        
        # Step 3: Format into readable sentences
        # Add proper sentence breaks
        cleaned = re.sub(r'([.!?])\s*([A-Z])', r'\1\n\n\2', cleaned)
        
        # Fix spacing around punctuation
        cleaned = re.sub(r'\s+([,.!?;:])', r'\1', cleaned)
        cleaned = re.sub(r'([.!?])\s*', r'\1 ', cleaned)
        
        # Step 4: Structure content with bullet points where appropriate
        # Look for policy points and format them
        if 'return' in cleaned.lower() or 'refund' in cleaned.lower():
            # Structure return/refund policies
            cleaned = self._format_return_policy(cleaned)
        elif 'warranty' in cleaned.lower():
            cleaned = self._format_warranty_policy(cleaned)
        elif 'privacy' in cleaned.lower() or 'data' in cleaned.lower():
            cleaned = self._format_privacy_policy(cleaned)
        
        return cleaned.strip()
    
    def _format_return_policy(self, text: str) -> str:
        """Format return policy text for better readability."""
        # Extract key return policy points
        formatted = text
        
        # Add structure for return timeframes
        if '7 days' in text:
            formatted = formatted.replace('within 7 days', '\n• Within 7 days')
        
        # Highlight key conditions
        if 'unopened item' in text:
            formatted = formatted.replace('unopened item', '\n• Unopened items only')
        
        if 'original packaging' in text:
            formatted = formatted.replace('original packaging', '\n• In original packaging')
        
        return formatted
    
    def _format_warranty_policy(self, text: str) -> str:
        """Format warranty policy text for better readability."""
        return text  # Basic formatting for now
    
    def _format_privacy_policy(self, text: str) -> str:
        """Format privacy policy text for better readability."""
        return text  # Basic formatting for now
    
    def correct_spelling(self, text: str) -> str:
        """Correct simple typos in the query."""
        try:
            return str(TextBlob(text).correct())
        except:
            return text  # Return original if correction fails
    
    def refine_policy_content(self, raw_content: str, user_query: str) -> str:
        """
        Use LLM to refine and clean up raw policy content for better user readability.
        
        Args:
            raw_content: Raw policy text from Pinecone
            user_query: User's original question for context
            
        Returns:
            Refined, clean, and user-friendly policy content
        """
        if not self.llm or not raw_content.strip():
            return raw_content
        
        try:
            refinement_prompt = f"""
You are a customer service assistant for Lotus Electronics. Clean up and refine this raw policy text to make it clear and user-friendly.

User's Question: "{user_query}"

Raw Policy Text:
{raw_content}

Instructions:
1. Fix spelling errors, spacing issues, and formatting problems
2. Make the text clear and easy to understand
3. Keep all important policy details intact
4. Use proper punctuation and grammar
5. Make it conversational but professional
6. Ensure it directly addresses the user's question
7. Remove any OCR artifacts or garbled text

Provide only the refined policy text, no additional commentary:
"""
            
            response = self.llm.invoke(refinement_prompt)
            refined_content = response.content.strip()
            
            # Validate that the refined content is reasonable
            if len(refined_content) > 50 and len(refined_content) < len(raw_content) * 3:
                return refined_content
            else:
                print(f"⚠️ LLM refinement produced unusual result, using original")
                return raw_content
                
        except Exception as e:
            print(f"⚠️ Error refining policy content: {e}")
            return raw_content
    
    def search_policies(self, query: str, max_results: int = 3) -> Dict[str, Any]:
        """
        Search Terms & Conditions and Privacy Policy documents.
        
        Args:
            query: User's question about policies
            max_results: Maximum number of results to return
            
        Returns:
            Dictionary containing relevant policy sections
        """
        if not self.is_available or not self.index or not self.model:
            return {
                "success": False,
                "error": "Terms & Conditions search service is currently unavailable",
                "policy_sections": []
            }
        
        try:
            # Correct spelling
            corrected_query = self.correct_spelling(query)
            if max_results <= 2:  # Only show debug info for test runs
                print(f"🔍 Searching for: '{corrected_query}'")
            
            # Embed the query
            query_embedding = self.model.encode(corrected_query).tolist()
            if max_results <= 2:  # Only show debug info for test runs
                print(f"📊 Query embedding dimension: {len(query_embedding)}")
            
            # Query Pinecone - match the working search_tc.py exactly
            results = self.index.query(
                vector=query_embedding,
                top_k=min(max_results, 5),
                include_metadata=True
            )
            
            if max_results <= 2:  # Only show debug info for test runs
                print(f"🔍 Raw Pinecone results: {len(results.get('matches', []))} matches found")
            
            # Process results - include ALL matches like the working version
            policy_sections = []
            for i, match in enumerate(results.get('matches', [])):
                score = match.get('score', 0.0)
                metadata = match.get('metadata', {})
                text = metadata.get('text', '').strip()  # Simple text extraction
                
                if max_results <= 2:  # Only show debug info for test runs
                    print(f"   Match {i+1}: Score={score:.4f}, Text length={len(text)}")
                
                # Include all results with text, no score filtering like search_tc.py
                if text:
                    # Apply enhanced text cleaning and formatting
                    cleaned_content = self.clean_and_format_text(text)
                    
                    # Use LLM refinement only if enabled and for high-relevance results
                    if self.use_llm_refinement and score >= 0.4:
                        refined_content = self.refine_policy_content(cleaned_content, corrected_query)
                    else:
                        refined_content = cleaned_content
                    
                    policy_sections.append({
                        "relevance_score": round(score, 4),
                        "content": refined_content,
                        "section_type": metadata.get('section_type', 'general'),
                        "document": metadata.get('document', 'terms_conditions')
                    })
            
            return {
                "success": True,
                "query": corrected_query,
                "policy_sections": policy_sections,
                "total_found": len(policy_sections)
            }
            
        except Exception as e:
            print(f"❌ Error searching T&C: {e}")
            return {
                "success": False,
                "error": f"Search failed: {str(e)}",
                "policy_sections": []
            }

# Initialize the tool instance in fast mode (no LLM refinement for speed)
tc_search_tool = TermsConditionsSearchTool(use_llm_refinement=False)

@tool("search_terms_conditions", args_schema=TermsConditionsInput)
def search_terms_conditions(query: str, max_results: int = 3) -> str:
    """
    Search Lotus Electronics Terms & Conditions and Privacy Policy documents.
    
    Use this tool when customers ask about:
    - Return and refund policies
    - Warranty terms and conditions
    - Privacy policy and data protection
    - Shipping and delivery terms
    - Customer rights and responsibilities
    - Payment terms and security
    - Company policies and guidelines
    
    Args:
        query: Customer's question about terms, conditions, or privacy policy
        max_results: Number of relevant policy sections to return (1-5)
        
    Returns:
        JSON string containing relevant policy information
    """
    
    # Validate inputs
    if not query or not query.strip():
        return json.dumps({
            "success": False,
            "error": "Please provide a specific question about our terms and conditions",
            "policy_sections": []
        })
    
    max_results = max(1, min(max_results, 5))  # Ensure between 1-5
    
    # Perform search
    result = tc_search_tool.search_policies(query.strip(), max_results)
    
    # Add helpful context for the chatbot
    if result.get("success") and result.get("policy_sections"):
        result["guidance"] = "I found relevant information in our policies. Please review these sections for complete details."
    elif result.get("success") and not result.get("policy_sections"):
        result["guidance"] = "I couldn't find specific information about that in our current policy documents. Please contact our customer service for detailed assistance."
    else:
        result["guidance"] = "I'm unable to search our policy documents right now. Please contact our customer service team for policy-related questions."
    
    return json.dumps(result, ensure_ascii=False, indent=2)

# Test function for standalone usage
def test_search():
    """Test function for the Terms & Conditions search tool."""
    test_queries = [
        "return policy",
        "warranty terms", 
        "privacy policy",
        "refund conditions",
        "data protection"
    ]
    
    print("🧪 Testing Terms & Conditions Search Tool")
    print("=" * 50)
    
    for query in test_queries:
        print(f"\n🔍 Testing query: '{query}'")
        # Call the underlying search function directly instead of the LangChain tool
        result = tc_search_tool.search_policies(query, 2)
        
        if result.get("success"):
            print(f"✅ Found {result.get('total_found', 0)} relevant sections")
            for i, section in enumerate(result.get("policy_sections", [])[:1], 1):
                content_preview = section.get("content", "")[:100] + "..."
                print(f"   {i}. Score: {section.get('relevance_score')} - {content_preview}")
        else:
            print(f"❌ Error: {result.get('error')}")
        print("-" * 30)

if __name__ == "__main__":
    test_search()
