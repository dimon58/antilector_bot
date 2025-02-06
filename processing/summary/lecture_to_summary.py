import logging
import subprocess
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt

from configs import PDFLATEX_EXECUTABLE, REQUIRED_LATEX_PACKAGES

logger = logging.getLogger(__name__)
markdown_parser = MarkdownIt("commonmark")


def _add_required_latex_packages(latex: str) -> str:
    _for_add = [pkg for pkg in REQUIRED_LATEX_PACKAGES if pkg not in latex]

    if len(_for_add) == 0:
        return latex

    idx = latex.find(r"\documentclass")
    new_line_idx = latex.find("\n", idx)

    part1 = latex[:new_line_idx]
    part2 = latex[new_line_idx + 1 :]

    return f"{part1}\n{'\n'.join(_for_add)}\n{part2}"


def extract_latex_from_llm_answer(parser: MarkdownIt, llm_answer: str) -> str | None:
    """
    Извлекает latex код из конспекта нейросети.

    Ответ обычно выглядит так:

    ```latex
    Какой-то код
    ```
    """

    ast = parser.parse(llm_answer)
    for token in ast:
        if token.type == "fence":
            return _add_required_latex_packages(token.content)

    return llm_answer


def _run_pdflatex(out_dir: Path, temp_latex: Path, out_pdf: Path, executable: str = "pdflatex") -> None:
    command = [
        executable,
        "-halt-on-error",
        "-interaction=nonstopmode",
        "-synctex=1",
        "-output-format=pdf",
        f"-output-directory={out_dir.absolute().as_posix()}",
        temp_latex.absolute().as_posix(),
    ]

    process = subprocess.Popen(  # noqa: S603 # nosec: B603, B607
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # universal_newlines=True,  # noqa: ERA001
    )
    buffer = []
    for out in process.stdout.readlines():
        text = out.strip()
        buffer.append(text)
        logger.debug(text)

    process.communicate()
    retcode = process.poll()
    if retcode and not out_pdf.exists():
        raise RuntimeError(f"Failed to render pdf: {'\n'.join(map(str, buffer))}")


def render_latex(latex: str, pdflatex_executable: str = PDFLATEX_EXECUTABLE) -> bytes:
    temp_name = "temp"
    with tempfile.TemporaryDirectory() as _tmpdir:
        temp_dir = Path(_tmpdir)
        temp_latex = temp_dir / f"{temp_name}.tex"
        with temp_latex.open("wb") as f:
            f.write(latex.encode("utf-8"))

        out_dir = temp_dir / "out"
        out_dir.mkdir(exist_ok=True)
        out_pdf = out_dir / f"{temp_name}.pdf"

        logger.info("Compiling latex: 1 pass")
        _run_pdflatex(out_dir, temp_latex, out_pdf, pdflatex_executable)
        logger.info("Compiling latex: 2 pass")
        _run_pdflatex(out_dir, temp_latex, out_pdf, pdflatex_executable)

        with out_pdf.open("rb") as f:
            return f.read()


def llm_answer_to_pdf(llm_answer: str, pdflatex_executable: str = PDFLATEX_EXECUTABLE) -> tuple[str, bytes]:
    """
    Компилирует ответ llm, содержащий latex, в pdf
    """
    latex = extract_latex_from_llm_answer(markdown_parser, llm_answer)
    return latex, render_latex(latex=latex, pdflatex_executable=pdflatex_executable)
