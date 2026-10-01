"""Public website endpoint, independent of chatbot sessions and tools."""
from flask import Blueprint, current_app, jsonify, request
from smart_search import SearchUnavailable, SmartSearch


def create_smart_search_blueprint(catalogue, ai_client):
    api = Blueprint("smart_search", __name__)
    service = SmartSearch(catalogue, ai_client)

    @api.post("/api/search/smart")
    def search():
        if request.content_length and request.content_length > 8192:
            return jsonify(status="error", error="Request body too large"), 413
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(status="error", error="A JSON object is required"), 400
        if set(body) - {"query", "page", "pageSize", "city", "brandMatch", "category"}:
            return jsonify(status="error", error="Supported fields: query, page, pageSize, city, brandMatch, category"), 400
        category = body.get("category", "all")
        if not isinstance(category, str) or not 1 <= len(category.strip()) <= 100:
            return jsonify(status="error", error="category must contain 1 to 100 characters"), 400
        query, city = body.get("query"), body.get("city", "INDORE")
        page, size = body.get("page", 1), body.get("pageSize", 24)
        brand_match = body.get("brandMatch", "family")
        if not isinstance(brand_match, str) or brand_match not in {"family", "exact"}:
            return jsonify(status="error", error="brandMatch must be family or exact"), 400
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 300:
            return jsonify(status="error", error="query must contain 2 to 300 characters"), 400
        if type(page) is not int or not 1 <= page <= 200 or type(size) is not int or not 1 <= size <= 48:
            return jsonify(status="error", error="page must be 1..200 and pageSize must be 1..48"), 400
        if not isinstance(city, str) or not 1 <= len(city.strip()) <= 100:
            return jsonify(status="error", error="city must contain 1 to 100 characters"), 400
        try:
            data = service.search(query.strip(), page, size, city.strip().upper(), brand_match=brand_match, category=category.strip())
            response = jsonify(status="success", data=data)
            response.headers["Cache-Control"] = "no-store"
            return response
        except ValueError as error:
            return jsonify(status="error", error=str(error)), 400
        except SearchUnavailable as error:
            return jsonify(status="error", error=str(error), error_code="smart_search_unavailable"), 503
        except Exception:
            current_app.logger.exception("Smart search failed")
            return jsonify(status="error", error="Smart search temporarily unavailable",
                           error_code="smart_search_unavailable"), 503

    return api
