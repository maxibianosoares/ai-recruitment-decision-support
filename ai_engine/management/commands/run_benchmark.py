"""
Usage:

    python manage.py run_benchmark
    python manage.py run_benchmark --category temporal
    python manage.py run_benchmark --format latex

Runs the RAG evaluation dataset (rag/evaluation/questions.py, 40
questions across 5 thesis categories) through the live RAG pipeline,
prints a summary table to the console, and writes:

  - rag/evaluation/results/benchmark_<timestamp>.json  (full raw data)
  - rag/evaluation/results/benchmark_<timestamp>.md     (Markdown table)
  - rag/evaluation/results/benchmark_<timestamp>.tex    (LaTeX table,
    only with --format latex or --format both)

Requires Ollama running locally with the gemma3:12b model loaded —
this hits the real pipeline, it does not mock anything.
"""

import os

from django.core.management.base import BaseCommand

from rag.evaluation.benchmark import evaluator


class Command(BaseCommand):

    help = (
        "Run the RAG benchmark question matrix through the live "
        "pipeline and generate a metrics table for the thesis paper."
    )

    def add_arguments(self, parser):

        parser.add_argument(
            "--category",
            type=str,
            default=None,
            help=(
                "Only run questions from one category: "
                "direct_evidence, partial_evidence, unsupported, "
                "temporal, recruitment_specific."
            )
        )

        parser.add_argument(
            "--format",
            type=str,
            default="markdown",
            choices=["markdown", "latex", "both"],
            help="Which table format(s) to write to disk."
        )

    def handle(self, *args, **options):

        category_filter = options.get("category")

        if category_filter:

            original_questions = evaluator.questions

            evaluator.questions = [
                q for q in original_questions
                if q.get("category") == category_filter
            ]

            if not evaluator.questions:

                self.stderr.write(
                    self.style.ERROR(
                        f"No questions found for category "
                        f"'{category_filter}'."
                    )
                )

                return

        self.stdout.write(
            self.style.NOTICE(
                f"Running {len(evaluator.questions)} benchmark "
                f"question(s) through the live RAG pipeline...\n"
                f"(this calls Ollama once per question — make sure "
                f"gemma3:12b is loaded)"
            )
        )

        results = evaluator.evaluate()

        metrics = evaluator.calculate_metrics(results)

        json_path = evaluator.save_results(results, metrics)

        base_path = os.path.splitext(json_path)[0]

        markdown_table = evaluator.render_markdown_table(metrics)

        md_path = base_path + ".md"

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown_table)

        output_format = options.get("format")

        tex_path = None

        if output_format in ("latex", "both"):

            latex_table = evaluator.render_latex_table(metrics)

            tex_path = base_path + ".tex"

            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(latex_table)

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(
            self.style.SUCCESS("RAG BENCHMARK SUMMARY")
        )
        self.stdout.write("=" * 70)
        self.stdout.write(markdown_table)

        self.stdout.write(
            self.style.SUCCESS(f"\nRaw results : {json_path}")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Markdown    : {md_path}")
        )

        if tex_path:
            self.stdout.write(
                self.style.SUCCESS(f"LaTeX       : {tex_path}")
            )
