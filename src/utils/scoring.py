from typing import Dict, List, Any


class InventionScorer:
    WEIGHTS = {
        "completeness": 30,
        "technical_depth": 25,
        "clarity": 20,
        "patent_readiness": 15,
        "confidence": 10
    }

    REQUIRED_FIELDS = [
        'invention_id', 'invention_name', 'technical_description',
        'problem_statement', 'solution_approach', 'key_technical_features',
        'statutory_category', 'domain_classification', 'inventor_keywords',
        'context'
    ]

    @staticmethod
    def score_invention(invention: Dict) -> Dict[str, Any]:
        completeness = InventionScorer._score_completeness(invention)
        technical_depth = InventionScorer._score_technical_depth(invention)
        clarity = InventionScorer._score_clarity(invention)
        patent_readiness = InventionScorer._score_patent_readiness(invention)
        confidence_score = InventionScorer._score_confidence(invention)

        total = (
            completeness * InventionScorer.WEIGHTS["completeness"] / 30 +
            technical_depth * InventionScorer.WEIGHTS["technical_depth"] / 25 +
            clarity * InventionScorer.WEIGHTS["clarity"] / 20 +
            patent_readiness * InventionScorer.WEIGHTS["patent_readiness"] / 15 +
            confidence_score * InventionScorer.WEIGHTS["confidence"] / 10
        )

        issues = InventionScorer._identify_issues(invention)

        return {
            "total_score": int(total),
            "rating": InventionScorer._get_rating(int(total)),
            "breakdown": {
                "completeness": f"{completeness}/{InventionScorer.WEIGHTS['completeness']}",
                "technical_depth": f"{technical_depth}/{InventionScorer.WEIGHTS['technical_depth']}",
                "clarity": f"{clarity}/{InventionScorer.WEIGHTS['clarity']}",
                "patent_readiness": f"{patent_readiness}/{InventionScorer.WEIGHTS['patent_readiness']}",
                "confidence": f"{confidence_score}/{InventionScorer.WEIGHTS['confidence']}"
            },
            "issues": issues,
            "recommendations": InventionScorer._generate_recommendations(issues)
        }

    @staticmethod
    def _score_completeness(invention: Dict) -> int:
        score = 0

        all_present = all(
            field in invention for field in InventionScorer.REQUIRED_FIELDS)
        if all_present:
            score += 10

        adequate_length = (
            len(str(invention.get('technical_description', ''))) >= 50 and
            len(str(invention.get('problem_statement', ''))) >= 30 and
            len(str(invention.get('solution_approach', ''))) >= 30
        )
        if adequate_length:
            score += 10

        no_placeholders = not any(
            placeholder in str(invention.get(field, '')).lower()
            for field in ['technical_description', 'problem_statement', 'solution_approach']
            for placeholder in ['n/a', 'unknown', 'tbd', 'todo']
        )
        if no_placeholders:
            score += 10

        return score

    @staticmethod
    def _score_technical_depth(invention: Dict) -> int:
        score = 0

        features = invention.get('key_technical_features', [])
        keywords = invention.get('inventor_keywords', [])

        if len(features) >= 5:
            score += 8
        elif len(features) >= 3:
            score += 5

        tech_terms = any(
            term in ' '.join(features + keywords).lower()
            for term in ['algorithm', 'system', 'method', 'process', 'network',
                         'model', 'architecture', 'mechanism', 'protocol']
        )
        if tech_terms:
            score += 10

        specific = all(len(feature) > 10 for feature in features[:5])
        if specific:
            score += 7

        return score

    @staticmethod
    def _score_clarity(invention: Dict) -> int:
        score = 0

        problem = invention.get('problem_statement', '')
        solution = invention.get('solution_approach', '')

        if len(problem.split('.')) >= 2:
            score += 7

        if len(solution.split('.')) >= 2:
            score += 7

        if 'problem' in problem.lower() or 'challenge' in problem.lower():
            score += 3
        if 'solution' in solution.lower() or 'approach' in solution.lower():
            score += 3

        return score

    @staticmethod
    def _score_patent_readiness(invention: Dict) -> int:
        score = 0

        valid_categories = ['Process', 'Machine',
                            'Manufacture', 'Composition of Matter']
        if invention.get('statutory_category') in valid_categories:
            score += 5

        domain = invention.get('domain_classification', '')
        if domain and len(domain) > 2:
            score += 5

        keywords = invention.get('inventor_keywords', [])
        if len(keywords) >= 5:
            score += 5

        return score

    @staticmethod
    def _score_confidence(invention: Dict) -> int:
        score = 0

        context = invention.get('context', {})
        conf_score = context.get('confidence_score', 0)

        if conf_score >= 0.8:
            score += 5
        elif conf_score >= 0.6:
            score += 3

        if context.get('document_section'):
            score += 5

        return score

    @staticmethod
    def _identify_issues(invention: Dict) -> List[str]:
        issues = []

        if len(invention.get('key_technical_features', [])) < 5:
            issues.append("Insufficient technical features (need 5+)")

        if len(str(invention.get('technical_description', ''))) < 50:
            issues.append("Technical description too brief")

        if invention.get('statutory_category') not in ['Process', 'Machine', 'Manufacture', 'Composition of Matter']:
            issues.append("Invalid statutory category")

        if len(invention.get('inventor_keywords', [])) < 5:
            issues.append("Insufficient keywords (need 5+)")

        return issues

    @staticmethod
    def _generate_recommendations(issues: List[str]) -> List[str]:
        recommendations = []

        for issue in issues:
            if "technical features" in issue:
                recommendations.append(
                    "Add 2-3 more specific technical features")
            elif "description too brief" in issue:
                recommendations.append(
                    "Expand technical description to 2-4 sentences")
            elif "statutory category" in issue:
                recommendations.append(
                    "Correct statutory category classification")
            elif "keywords" in issue:
                recommendations.append("Add more relevant technical keywords")

        return recommendations

    @staticmethod
    def _get_rating(score: int) -> str:
        if score >= 90:
            return "5/5 Excellent"
        if score >= 80:
            return "4/5 Good"
        if score >= 70:
            return "3/5 Fair"
        if score >= 60:
            return "2/5 Poor"
        return "1/5 Inadequate"
