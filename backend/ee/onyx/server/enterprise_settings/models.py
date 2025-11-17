from typing import Any

from pydantic import BaseModel, Field


class NavigationItem(BaseModel):
    """Элемент навигации для кастомного меню системы"""

    link: str = Field(
        description="URL ссылка для перехода при клике на элемент навигации"
    )
    title: str = Field(
        description="Текст заголовка элемента навигации для отображения в меню"
    )

    icon: str | None = Field(
        default=None,
        description="Название Font Awesome иконки для отображения рядом с заголовком"
    )

    svg_logo: str | None = Field(
        default=None,
        description="SVG логотип в виде строки. ВНИМАНИЕ: SVG не должен содержать width/height атрибутов"
    )

    @classmethod
    def model_validate(cls, *args: Any, **kwargs: Any) -> "NavigationItem":
        """Валидирует данные элемента навигации.

        Проверяет что указана ровно одна из опций: Font Awesome иконка или SVG логотип.

        Args:
            *args: Позиционные аргументы для валидации
            **kwargs: Именованные аргументы для валидации

        Returns:
            Валидированный экземпляр NavigationItem

        Raises:
            ValueError: Если не указана или указаны обе опции иконки/логотипа
        """
        # Создаем экземпляр через базовую валидацию
        validated_instance = super().model_validate(*args, **kwargs)

        # Проверяем что указана ровно одна опция для отображения
        has_icon = bool(validated_instance.icon)
        has_svg_logo = bool(validated_instance.svg_logo)

        if has_icon == has_svg_logo:
            error_message = "Должна быть указана ровно одна опция: icon или svg_logo"
            raise ValueError(error_message)

        return validated_instance


class EnterpriseSettings(BaseModel):
    """Настройки системы.

    Содержит параметры для кастомизации интерфейса, навигации и компонентов системы.
    ВНИМАНИЕ: не размещайте чувствительные данные в этих настройках,
    так как они доступны без аутентификации.
    """

    application_name: str | None = Field(
        default=None,
        description="Кастомное название приложения для отображения в интерфейсе"
    )
    use_custom_logo: bool = Field(
        default=False,
        description="Использовать кастомный логотип вместо стандартного"
    )
    use_custom_logotype: bool = Field(
        default=False,
        description="Использовать кастомный текстовый логотип"
    )

    # Кастомизация навигации
    custom_nav_items: list[NavigationItem] = Field(
        default_factory=list,
        description="Список кастомных элементов навигации для бокового меню"
    )


    # Кастомизация компонентов чата
    two_lines_for_chat_header: bool | None = Field(
        default=None,
        description="Отображать заголовок чата в две строки вместо одной"
    )
    custom_lower_disclaimer_content: str | None = Field(
        default=None,
        description="Кастомный текст дисклеймера в нижней части интерфейса"
    )
    custom_header_content: str | None = Field(
        default=None,
        description="Кастомное содержимое заголовка страницы"
    )
    custom_popup_header: str | None = Field(
        default=None,
        description="Заголовок кастомного всплывающего окна"
    )
    custom_popup_content: str | None = Field(
        default=None,
        description="Содержимое кастомного всплывающего окна"
    )
    enable_consent_screen: bool | None = Field(
        default=None,
        description="Включить экран согласия при первом входе"
    )

    def check_validity(self) -> None:
        """Проверяет валидность настроек.

        В текущей реализации проверки не выполняются, метод оставлен
        для обратной совместимости и будущих расширений.
        """
        return


class AnalyticsScriptUpload(BaseModel):
    """Модель для загрузки кастомного аналитического скрипта"""

    script: str = Field(
        description="Код JavaScript скрипта аналитики для внедрения в систему"
    )
    secret_key: str = Field(
        description="Секретный ключ для проверки прав доступа при загрузке скрипта"
    )
