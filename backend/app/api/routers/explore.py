from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.song_explorer_service import SongExplorerService


router = APIRouter(prefix="/explore", tags=["explore"])


@router.get("/song/search")
async def search_song(keyword: str = Query(..., min_length=1)) -> dict:
    return await SongExplorerService().search_song(keyword)


@router.get("/song/ai-analysis")
def song_ai_analysis(song_name: str = Query(..., min_length=1), artist_name: str = "") -> dict[str, str]:
    return SongExplorerService().generate_ai_analysis(song_name, artist_name)


@router.delete("/session/{session_id}")
def cleanup_session(session_id: str) -> dict:
    return SongExplorerService().cleanup_session_cache(session_id)
