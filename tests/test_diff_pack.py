"""
Tests for diff packing - fitting a change set's diffs into a token budget
without cutting mid-line, showing the riskiest files first, and reporting
honestly what the model did not see.
"""

import pytest

from semantic_diff.diff_pack import Tier, classify, estimate_tokens, pack
from semantic_diff.models import DiffCoverage, FileChange


def _hunk(start: int, added: int = 1, removed: int = 1, width: int = 10) -> str:
    body = [f"-{'o' * width}" for _ in range(removed)] + [f"+{'n' * width}" for _ in range(added)]
    return f"@@ -{start},{removed} +{start},{added} @@\n" + "\n".join(body)


def _file(path: str, *hunks: str, change_type: str = "modified") -> FileChange:
    content = "\n".join(hunks)
    lines = content.split("\n")
    return FileChange(
        path=path,
        change_type=change_type,
        additions=sum(1 for line in lines if line.startswith("+")),
        deletions=sum(1 for line in lines if line.startswith("-")),
        diff_content=content,
    )


class TestClassify:
    @pytest.mark.parametrize(
        "path",
        [
            "pnpm-lock.yaml",
            "frontend/package-lock.json",
            "yarn.lock",
            "poetry.lock",
            "uv.lock",
            "Cargo.lock",
            "go.sum",
            "src/__snapshots__/view.test.ts.snap",
            "services/api/src/db/migrations/meta/_journal.json",
            "services/api/src/db/migrations/meta/0063_snapshot.json",
            "dist/index.js",
            "packages/ui/build/main.css",
            "node_modules/x/index.js",
            "static/app.min.js",
            "static/app.min.css",
            "static/app.js.map",
        ],
    )
    def test_generated_and_lock_files_are_noise(self, path):
        assert classify(path) is Tier.NOISE

    @pytest.mark.parametrize(
        "path, tier",
        [
            ("semantic_diff/cli.py", Tier.CODE),
            ("services/api/src/routes/chat.ts", Tier.CODE),
            ("services/api/src/db/migrations/0063_add_owner.sql", Tier.MIGRATION),
            ("db/schema.sql", Tier.MIGRATION),
            ("alembic/migrations/versions/abc_add.py", Tier.MIGRATION),
            (".gitlab-ci.yml", Tier.INFRA),
            ("ci/security.yml", Tier.INFRA),
            ("infra/helm/agentic/charts/api/values.yaml", Tier.INFRA),
            ("Dockerfile", Tier.INFRA),
            ("services/api/Dockerfile.worker", Tier.INFRA),
            ("terraform/main.tf", Tier.INFRA),
            (".github/workflows/ci.yml", Tier.INFRA),
            ("tests/test_cli.py", Tier.TEST),
            ("services/api/src/routes/chat.test.ts", Tier.TEST),
            ("tests/e2e/login.spec.ts", Tier.TEST),
            ("pkg/server_test.go", Tier.TEST),
            ("README.md", Tier.DOCS),
            ("docs/ARCHITECTURE.md", Tier.DOCS),
            ("CHANGELOG.rst", Tier.DOCS),
        ],
    )
    def test_tiers(self, path, tier):
        assert classify(path) is tier

    def test_tiers_order_code_first_docs_last(self):
        assert Tier.CODE < Tier.MIGRATION < Tier.INFRA < Tier.TEST < Tier.DOCS < Tier.NOISE

    def test_test_fixture_sql_is_a_test_not_a_migration(self):
        assert classify("tests/fixtures/seed.sql") is Tier.TEST

    def test_renamed_file_is_classified_by_its_new_path(self):
        assert classify("tests/old.py -> src/new.py") is Tier.CODE

    def test_rename_into_a_path_with_spaces(self):
        assert classify("src/a.py -> my tests/x.py") is Tier.CODE

    def test_any_file_under_docs_is_docs(self):
        assert classify("docs/diagram.svg") is Tier.DOCS

    def test_any_file_under_an_infra_dir_is_infra(self):
        assert classify("infra/helm/api/templates/_helpers.tpl") is Tier.INFRA


class TestEstimateTokens:
    def test_three_and_a_half_chars_per_token_rounded_up(self):
        assert estimate_tokens("x" * 7) == 2
        assert estimate_tokens("x" * 8) == 3

    def test_empty_text_costs_nothing(self):
        assert estimate_tokens("") == 0


class TestPackWithinBudget:
    def test_everything_fits_everything_is_shown_whole(self):
        files = [_file("a.py", _hunk(1)), _file("b.py", _hunk(1), _hunk(20))]

        result = pack(files, budget_tokens=10_000)

        assert [(s.file.path, s.text) for s in result.shown] == [
            ("a.py", files[0].diff_content),
            ("b.py", files[1].diff_content),
        ]
        assert result.coverage == DiffCoverage(budget_tokens=10_000, shown_lines=6, total_lines=6)
        assert result.coverage.percent == 100

    def test_files_are_shown_riskiest_tier_first_stable_within_tier(self):
        files = [
            _file("README.md", _hunk(1)),
            _file("tests/test_a.py", _hunk(1)),
            _file("b.py", _hunk(1)),
            _file("db/0001.sql", _hunk(1)),
            _file("a.py", _hunk(1)),
            _file(".gitlab-ci.yml", _hunk(1)),
        ]

        result = pack(files, budget_tokens=10_000)

        assert [s.file.path for s in result.shown] == [
            "b.py",
            "a.py",
            "db/0001.sql",
            ".gitlab-ci.yml",
            "tests/test_a.py",
            "README.md",
        ]


class TestPackOverBudget:
    def test_budget_is_inclusive_an_exact_fit_is_shown_whole(self):
        content = "\n".join([_hunk(1), _hunk(50), _hunk(99)])
        exact = estimate_tokens(content)

        result = pack([_file("a.py", content)], budget_tokens=exact)

        assert [(s.text, s.trimmed) for s in result.shown] == [(content, False)]

    def test_budget_is_spent_across_all_files(self):
        files = [_file(f"f{i}.py", _hunk(1, width=100)) for i in range(3)]
        each = estimate_tokens(files[0].diff_content)

        result = pack(files, budget_tokens=2 * each + 1)

        assert [s.file.path for s in result.shown] == ["f0.py", "f1.py"]
        assert result.coverage.omitted == ["f2.py"]

    def test_trims_a_file_at_hunk_boundaries_never_mid_line(self):
        hunks = [_hunk(1, width=200), _hunk(50, width=200), _hunk(99, width=200)]
        big = _file("core.py", *hunks)
        budget = estimate_tokens("\n".join(hunks[:2])) + 1

        result = pack([big], budget_tokens=budget)

        [shown] = result.shown
        assert shown.text == "\n".join(hunks[:2])
        assert (shown.hunks_shown, shown.hunks_total) == (2, 3)
        assert shown.trimmed
        assert result.coverage.trimmed == ["core.py"]
        assert result.coverage.shown_lines == 4
        assert result.coverage.total_lines == 6

    def test_file_whose_first_hunk_does_not_fit_is_omitted_not_cut(self):
        huge = _file("core.py", _hunk(1, width=5_000))

        result = pack([huge], budget_tokens=100)

        assert result.shown == []
        assert result.coverage.omitted == ["core.py"]
        assert result.coverage.shown_lines == 0
        assert result.coverage.percent == 0

    def test_smaller_later_files_still_fill_the_remaining_budget(self):
        huge = _file("core.py", _hunk(1, width=5_000))
        small = _file("util.py", _hunk(1))

        result = pack([huge, small], budget_tokens=100)

        assert [s.file.path for s in result.shown] == ["util.py"]
        assert result.coverage.omitted == ["core.py"]

    def test_lower_tier_gives_way_to_higher_tier(self):
        code = _file("core.py", _hunk(1, width=300))
        docs = _file("README.md", _hunk(1, width=300))
        budget = estimate_tokens(code.diff_content) + 1

        result = pack([docs, code], budget_tokens=budget)

        assert [s.file.path for s in result.shown] == ["core.py"]
        assert result.coverage.omitted == ["README.md"]

    def test_coverage_percent_is_shown_over_total_changed_lines(self):
        shown_file = _file("a.py", _hunk(1, added=3, removed=0))
        omitted = _file("b.py", _hunk(1, added=1, removed=0, width=5_000))

        result = pack([shown_file, omitted], budget_tokens=100)

        assert (result.coverage.shown_lines, result.coverage.total_lines) == (3, 4)
        assert result.coverage.percent == 75

    def test_percent_is_rounded_down_so_partial_never_reads_as_full(self):
        assert DiffCoverage(budget_tokens=1, shown_lines=999, total_lines=1000).percent == 99


class TestPackNoise:
    def test_noise_content_is_never_shown_and_not_counted_in_coverage(self):
        lock = _file("pnpm-lock.yaml", _hunk(1, added=500, removed=0))
        code = _file("a.py", _hunk(1))

        result = pack([lock, code], budget_tokens=10_000)

        assert [s.file.path for s in result.shown] == ["a.py"]
        assert result.coverage.noise == ["pnpm-lock.yaml"]
        assert result.coverage.total_lines == 2
        assert result.coverage.percent == 100

    def test_binary_file_is_noise(self):
        binary = FileChange(
            path="logo.png",
            change_type="modified",
            diff_content="Binary files a/logo.png and b/logo.png differ\n",
        )

        result = pack([binary], budget_tokens=10_000)

        assert result.shown == []
        assert result.coverage.noise == ["logo.png"]


class TestPackEdgeCases:
    def test_file_without_content_is_not_shown_and_costs_nothing(self):
        pure_rename = FileChange(path="a.py -> b.py", change_type="renamed", diff_content="")

        result = pack([pure_rename], budget_tokens=10)

        assert result.shown == []
        assert result.coverage == DiffCoverage(budget_tokens=10, shown_lines=0, total_lines=0)
        assert result.coverage.percent == 100

    def test_content_without_hunk_headers_is_one_hunk(self):
        initial = _file("new.py", "+line one\n+line two", change_type="added")

        result = pack([initial], budget_tokens=10_000)

        assert [(s.text, s.hunks_total) for s in result.shown] == [("+line one\n+line two", 1)]

    def test_text_before_the_first_hunk_is_its_own_piece(self):
        content = "preamble\n" + _hunk(1) + "\n" + _hunk(9)

        [shown] = pack([_file("a.py", content)], budget_tokens=10_000).shown

        assert (shown.text, shown.hunks_total) == (content, 3)

    def test_hunks_keep_trailing_blank_context_lines(self):
        content = "@@ -1,2 +1,2 @@\n-a\n+b\n \n" + "@@ -9 +9 @@\n-c\n+X"

        [shown] = pack([_file("a.py", content)], budget_tokens=10_000).shown

        assert shown.text == content

    def test_context_lines_do_not_count_as_changed(self):
        with_context = _file("a.py", "@@ -1,3 +1,3 @@\n keep\n-old\n+new\n keep")

        result = pack([with_context], budget_tokens=10_000)

        assert result.coverage.total_lines == 2

    def test_empty_change_set(self):
        result = pack([], budget_tokens=10)

        assert result.shown == []
        assert result.coverage.percent == 100

    def test_one_token_budget_is_allowed(self):
        assert pack([], budget_tokens=1).coverage.budget_tokens == 1

    def test_budget_must_be_positive(self):
        with pytest.raises(ValueError, match="budget"):
            pack([], budget_tokens=0)
