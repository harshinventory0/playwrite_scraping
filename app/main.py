import os
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, validator

from app.scraper import ScraperError, get_env_credentials, run_scraper

app = FastAPI(
    title='CourseFinder Scraper API',
    description='API that accepts a list of search terms and downloads top 25 results for each query.',
    version='0.1.0',
)


class SearchRequest(BaseModel):
    queries: List[str] = Field(..., min_items=1, description='List of search terms.')
    headless: Optional[bool] = Field(
        None,
        description='Optional override for the browser headless mode. If omitted, HEADLESS from .env is used.',
    )

    @validator('queries', each_item=True)
    def non_empty_query(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError('Search terms must not be empty.')
        return value.strip()


class SearchResult(BaseModel):
    query: str
    success: bool
    filename: Optional[str] = None
    error: Optional[str] = None


class SearchResponse(BaseModel):
    results: List[SearchResult]


@app.get('/health')
def health_check() -> Dict[str, str]:
    return {'status': 'ok'}


@app.post('/search', response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    if not request.queries:
        raise HTTPException(status_code=400, detail='At least one search term is required.')

    try:
        email, password = get_env_credentials()
    except ScraperError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        results = run_scraper(email, password, request.queries, headless=request.headless)
    except ScraperError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return SearchResponse(results=[SearchResult(**result) for result in results])
