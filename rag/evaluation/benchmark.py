import json
import os
from datetime import datetime

from rag.rag_pipeline import rag_pipeline
from rag.evaluation.questions import BENCHMARK_QUESTIONS


class RAGEvaluator:

    def __init__(self):

        self.questions = BENCHMARK_QUESTIONS

    def evaluate(self):

        results = []

        for item in self.questions:

            question = item["question"]
            expected = item["expected"]

            print("\n" + "=" * 70)
            print(f"ID       : {item['id']}")
            print(f"QUESTION : {question}")
            print(f"EXPECTED : {expected}")

            try:

                result = rag_pipeline.ask(question)

                actual = result.get(
                    "evidence_status",
                    "unknown"
                )

                retrieval_status = result.get(
                    "retrieval_status",
                    "unknown"
                )

                evidence_coverage = result.get(
                    "evidence_coverage",
                    0
                )

                confidence = result.get(
                    "confidence",
                    0
                )

                evidence = result.get(
                    "evidence",
                    []
                )

                grounded = result.get(
                    "grounded",
                    False
                )

                unsupported_claims = result.get(
                    "unsupported_claims",
                    []
                )

                best_score = 0

                if evidence:

                    best_score = max(
                        item.get("score", 0)
                        for item in evidence
                    )

                classification_correct = (
                    actual == expected
                )

                result_item = {

                    "id":
                        item["id"],

                    "question":
                        question,

                    "expected":
                        expected,

                    "actual":
                        actual,

                    "retrieval_status":
                        result.get(
                            "retrieval_status",
                            "unknown"
                        ),

                    "coverage_status":
                        result.get(
                            "coverage_status",
                            "unknown"
                        ),

                    "coverage":
                        result.get(
                            "coverage",
                            0
                        ),

                    "classification_correct":
                        classification_correct,

                    "best_evidence_score":
                        best_score,

                    "confidence":
                        confidence,

                    "grounded":
                        grounded,

                    "unsupported_claims":
                        unsupported_claims,

                    "answer":
                        result.get(
                            "answer",
                            ""
                        ),

                    "sources":
                        result.get(
                            "sources",
                            []
                        )
                }

                results.append(result_item)

                print(
                    f"ACTUAL   : {actual}"
                )

                print(
                    f"EVIDENCE : {best_score:.4f}"
                )

                print(
                    f"GROUNDed : {grounded}"
                )

                print(
                    f"CORRECT  : {classification_correct}"
                )

            except Exception as e:

                print(
                    f"ERROR: {e}"
                )

                results.append({

                    "id": item["id"],

                    "question": question,

                    "expected": expected,

                    "actual": "error",

                    "classification_correct":
                        False,

                    "best_evidence_score": 0,

                    "confidence": 0,

                    "grounded": False,

                    "unsupported_claims": [],

                    "answer": "",

                    "sources": [],

                    "error": str(e)
                })

        return results

    def calculate_metrics(self, results):

        total = len(results)

        correct = sum(
            1
            for r in results
            if r["classification_correct"]
        )

        accuracy = (
            correct / total
            if total
            else 0
        )

        supported = [
            r for r in results
            if r["expected"] == "supported"
        ]

        partially_supported = [
            r for r in results
            if r["expected"] == "partially_supported"
        ]

        unsupported = [
            r for r in results
            if r["expected"] == "unsupported"
        ]

        supported_correct = sum(
            1
            for r in supported
            if r["actual"] == "supported"
        )

        unsupported_correct = sum(
            1
            for r in unsupported
            if r["actual"] == "unsupported"
        )

        partial_correct = sum(
            1
            for r in partially_supported
            if r["actual"] == "partially_supported"
        )

        false_acceptance = sum(
            1
            for r in unsupported
            if r["actual"] != "unsupported"
        )

        false_rejection = sum(
            1
            for r in supported
            if r["actual"] != "supported"
        )

        avg_evidence = (
            sum(
                r["best_evidence_score"]
                for r in results
            ) / total
            if total
            else 0
        )

        grounded_count = sum(
            1
            for r in results
            if r["grounded"]
        )

        grounded_rate = (
            grounded_count / total
            if total
            else 0
        )

        return {

            "total_questions": total,

            "classification_accuracy":
                accuracy,

            "supported_accuracy": (
                supported_correct / len(supported)
                if supported
                else 0
            ),

            "partial_accuracy": (
                partial_correct / len(partially_supported)
                if partially_supported
                else 0
            ),

            "unsupported_accuracy": (
                unsupported_correct / len(unsupported)
                if unsupported
                else 0
            ),

            "average_evidence_score":
                avg_evidence,

            "grounded_rate":
                grounded_rate,

            "false_acceptance":
                false_acceptance,

            "false_rejection":
                false_rejection
        }

    def save_results(
        self,
        results,
        metrics
    ):

        os.makedirs(
            "rag/evaluation/results",
            exist_ok=True
        )

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        output = {

            "timestamp":
                timestamp,

            "metrics":
                metrics,

            "results":
                results
        }

        path = (
            f"rag/evaluation/results/"
            f"benchmark_{timestamp}.json"
        )

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                output,
                f,
                indent=4,
                ensure_ascii=False
            )

        return path


evaluator = RAGEvaluator()