from __future__ import annotations

import re
from typing import Any


STOPWORDS = {
    "this", "that", "with", "from", "your", "what", "when", "where", "have", "they", "them", "about", "there",
    "were", "will", "would", "could", "should", "because", "actually", "really", "just", "then", "than", "into",
    "and", "the", "for", "you", "are", "was", "but", "not", "its", "his", "her", "their", "our", "how", "why",
}


def _clean(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _source_text(clip: dict[str, Any]) -> str:
    transcript = clip.get("transcript") or []
    return _clean(" ".join(str(item.get("text", "")) for item in transcript))


def _keywords(text: str, category: str) -> list[str]:
    words = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9'-]{3,}", text.lower()):
        if word in STOPWORDS or word in words:
            continue
        words.append(word)
        if len(words) >= 8:
            break
    if category.lower() not in words:
        words.insert(0, category.lower())
    return words[:8]


def _unique(values: list[str], limit: int = 5) -> list[str]:
    output: list[str] = []
    for value in values:
        value = _clean(value).rstrip(".")
        if value and value.lower() not in {item.lower() for item in output}:
            output.append(value[:160])
    return output[:limit]


def _topic_phrase(text: str, category: str) -> str:
    if text:
        return " ".join(text.split()[:12]).rstrip(".!?")
    return f"this {category.lower()} moment"


def _seo_score(title: str, description: str, keywords: list[str], hashtags: list[str], category: str) -> dict[str, Any]:
    title_score = 56
    if 25 <= len(title) <= 75:
        title_score += 25
    if category.lower() in title.lower():
        title_score += 8
    description_score = 45
    if 70 <= len(description) <= 300:
        description_score += 35
    if keywords and any(word in description.lower() for word in keywords[:2]):
        description_score += 10
    keyword_score = min(100, 45 + len(set(keywords)) * 7)
    hashtag_score = min(100, 48 + min(6, len(hashtags)) * 8)
    clarity = 86 if title and description else 35
    click = min(96, round((title_score * 0.35) + (description_score * 0.2) + (keyword_score * 0.15) + (hashtag_score * 0.15) + (clarity * 0.15)))
    score = round((title_score + description_score + keyword_score + hashtag_score + clarity) / 5)
    suggestions = []
    if title_score < 80:
        suggestions.append("Make the title more specific while keeping the actual topic clear.")
    if description_score < 80:
        suggestions.append("Add the primary topic naturally to the first sentence of the description.")
    if len(keywords) < 4:
        suggestions.append("Add a few more precise topic keywords extracted from the clip.")
    if len(hashtags) > 12:
        suggestions.append("Reduce broad hashtags and keep only the most relevant ones.")
    if not suggestions:
        suggestions.append("SEO signals are balanced; review the preview and keep the wording natural.")
    return {
        "score": max(0, min(100, score)),
        "title": round(title_score), "description": round(description_score), "keywords": round(keyword_score),
        "hashtags": round(hashtag_score), "clarity": round(clarity), "click_potential": click,
        "suggestions": suggestions,
    }


class AIProvider:
    provider_id = "base"

    def analyze_video(self, transcript: list[dict[str, Any]], scenes: list[dict[str, Any]], audio: list[dict[str, Any]]) -> dict[str, Any]:
        raise NotImplementedError

    def detect_highlights(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def generate_content_pack(self, clip: dict[str, Any], language: str = "en", tone: str = "casual", variant: int = 0) -> dict[str, Any]:
        raise NotImplementedError

    def generate_hook(self, clip: dict[str, Any], variant: int = 0) -> list[str]:
        return self.generate_content_pack(clip, variant=variant).get("hooks", [])

    def generate_title(self, clip: dict[str, Any], variant: int = 0) -> list[str]:
        return self.generate_content_pack(clip, variant=variant).get("titles", [])

    def generate_description(self, clip: dict[str, Any], variant: int = 0) -> dict[str, str]:
        return self.generate_content_pack(clip, variant=variant).get("description", {})

    def generate_hashtags(self, clip: dict[str, Any], variant: int = 0) -> dict[str, list[str]]:
        return self.generate_content_pack(clip, variant=variant).get("hashtags", {})

    def generate_keywords(self, clip: dict[str, Any], variant: int = 0) -> dict[str, Any]:
        return self.generate_content_pack(clip, variant=variant).get("keywords", {})

    def generate_seo(self, clip: dict[str, Any], variant: int = 0) -> dict[str, Any]:
        return self.generate_content_pack(clip, variant=variant).get("seo", {})

    def categorize_clip(self, clip: dict[str, Any]) -> str:
        return str(clip.get("category", "OTHER"))

    def score_clip(self, clip: dict[str, Any]) -> float:
        return float(clip.get("score", 0))


class LocalAIProvider(AIProvider):
    provider_id = "local-deterministic"

    def analyze_video(self, transcript: list[dict[str, Any]], scenes: list[dict[str, Any]], audio: list[dict[str, Any]]) -> dict[str, Any]:
        return {"provider": self.provider_id, "transcript_segments": len(transcript), "scenes": len(scenes), "audio_windows": len(audio), "network_calls": 0}

    def detect_highlights(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(candidates, key=lambda item: float(item.get("score", 0)), reverse=True)

    def generate_content_pack(self, clip: dict[str, Any], language: str = "en", tone: str = "casual", variant: int = 0) -> dict[str, Any]:
        category = str(clip.get("category", "INTERESTING")).upper()
        text = _source_text(clip)
        topic = _topic_phrase(text, category)
        keywords = _keywords(text, category)
        primary = f"{category.lower()} {keywords[1] if len(keywords) > 1 else 'short clip'}"
        secondary = _unique([f"{word} {category.lower()}" for word in keywords[1:5]] + [f"{category.lower()} moments", "short form video"], 5)
        long_tail = _unique([f"best {category.lower()} moments from this video", f"{primary} short video", f"{tone} {category.lower()} clip"], 3)
        broad_tags = [f"#{category.title().replace(' ', '')}", "#Shorts", "#Reels"]
        topic_tags = [f"#{word.title()}" for word in keywords[1:4]]
        hashtags = _unique(broad_tags + topic_tags, 10)
        if text:
            short_description = f"A {category.lower()} moment about {topic}."
            medium_description = f"This {category.lower()} clip captures: {topic}. Review the full context before publishing."
            long_description = f"A {category.lower()} short-form clip selected from the source video. The moment focuses on {topic}. The wording is based on the available transcript and should be reviewed for accuracy before publishing."
        else:
            short_description = f"A {category.lower()} moment selected from the source video."
            medium_description = "A short-form moment selected using local audio and visual signals. Review the preview because speech was not available for this clip."
            long_description = "This clip was selected from the source video using local scene and audio analysis. It does not claim facts beyond the source content."
        title_base = _clean(clip.get("title") or topic)
        title_options_en = _unique([
            title_base,
            f"The {category.title()} Moment From This Video",
            f"Nobody Expected This {category.title()} Moment",
            f"Watch This {category.title()} Clip Until The End",
            f"A {category.title()} Take That Stands Out",
        ], 5)
        hook_options_en = _unique([
            clip.get("hook") or f"Listen to this: {topic}",
            f"Wait until you hear this {category.lower()} moment...",
            f"This is where the conversation changes.",
            f"The context makes this moment even better.",
            f"Watch what happens next.",
        ], 5)
        if language.lower().startswith("hi"):
            title_options = _unique([
                title_base,
                f"इस {category.lower()} पल को ज़रूर देखें",
                "किसी ने इस जवाब की उम्मीद नहीं की थी",
                "अंत तक देखिए, असली बात वहीं है",
                "इस बातचीत का सबसे यादगार पल",
            ], 5)
            hook_options = _unique([
                f"आगे क्या हुआ, ज़रूर सुनिए...",
                "इस जवाब ने पूरी बातचीत बदल दी।",
                "अंत तक देखिए।",
                "यह पल संदर्भ के साथ और भी खास है।",
                "किसी ने इसकी उम्मीद नहीं की थी।",
            ], 5)
        else:
            title_options, hook_options = title_options_en, hook_options_en
        primary_title = title_options[variant % len(title_options)] if title_options else title_base
        primary_hook = hook_options[variant % len(hook_options)] if hook_options else "Watch this moment."
        seo = _seo_score(primary_title, medium_description, [primary, *secondary], hashtags, category)
        platform_versions = {
            "youtube_shorts": {
                "title": primary_title, "description": long_description, "keywords": [primary, *secondary, *long_tail], "hashtags": hashtags[:8]
            },
            "instagram_reels": {
                "caption": f"{primary_hook}\n\n{medium_description}", "keywords": [primary, *secondary[:3]], "hashtags": hashtags[:10]
            },
            "tiktok": {
                "caption": f"{primary_hook} {medium_description}", "search_terms": [primary, *secondary[:4]], "hashtags": hashtags[:8]
            },
            "facebook": {
                "caption": primary_title, "description": medium_description, "keywords": [primary, *secondary[:4]], "hashtags": hashtags[:8]
            },
        }
        return {
            "provider": self.provider_id, "notice": "Generated locally without a paid AI API.", "language": language, "tone": tone,
            "hook": primary_hook, "hooks": hook_options, "title": primary_title, "titles": title_options,
            "description": {"short": short_description, "medium": medium_description, "long": long_description},
            "hashtags": {"broad": broad_tags, "niche": topic_tags, "topic": [f"#{word.title()}" for word in keywords[1:5]], "all": hashtags},
            "keywords": {"primary": primary, "secondary": secondary, "long_tail": long_tail, "related": keywords},
            "seo": seo, "platforms": platform_versions,
        }


_provider = LocalAIProvider()


def generate_content_pack(clip: dict[str, Any], language: str = "en", tone: str = "casual", variant: int = 0) -> dict[str, Any]:
    return _provider.generate_content_pack(clip, language, tone, variant)
