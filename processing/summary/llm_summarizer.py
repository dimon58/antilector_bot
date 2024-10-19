from openai import OpenAI
from openai.types.chat import ChatCompletion

from configs import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
)

prompt_template = r"""Представь себя профессиональным составителем конспектов.
Сейчас тебе будет передана транскрипция лекции.
Она была сделана с помощью от нейросетевой модели whisper large v3 в теге <transcription></transcription>.
В самой транскрипции могут быть небольшие неточности (не правильно распознанные слова), постарайся их исправить.
Название лекции название будет передано в теге <title></title>.
Описание лекции будет передано в теге <description></description>. В описании может быть не очень много информации.
ТВОЯ ЗАДАЧУ БУДЕТ СОСТАВИТЬ НА ОСНОВЕ ТРАНСКРИБАЦИИ ПОДРОБНЫЙ КОНСПЕКТ LATEX.
СТАРАЙСЯ СОХРАНИТЬ ВСЕ ДЕТАЛИ И ПЕРЕДАТЬ ВСЕ МЫСЛИ ЛЕКТОРА.

<title>
{title}
</title>
<description>
{description}
</description>
<transcription>
{transcription}
</transcription>"""


def transcription_to_summary(title: str, description: str, transcription: str) -> ChatCompletion:
    prompt = prompt_template.format(
        title=title,
        description=description,
        transcription=transcription,
    )

    return client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
