"""文字入力欄以外を操作したときに画面キーボードを閉じる。"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit, QWidget


def is_text_input(widget):
    return isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)) and widget.isEnabled() and not widget.isReadOnly()


class InputFocusController(QObject):
    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self.osk = None
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface
            self.osk = QDBusInterface('sm.puri.OSK0', '/sm/puri/OSK0', 'sm.puri.OSK0',
                                      QDBusConnection.sessionBus(), self)
        except (ImportError, RuntimeError):
            pass
        app.installEventFilter(self)
        app.focusChanged.connect(self._focus_changed)

    def _hide_keyboard(self):
        QGuiApplication.inputMethod().hide()
        if self.osk is not None and self.app.applicationState() == Qt.ApplicationState.ApplicationActive:
            self.osk.asyncCallWithArgumentList('SetVisible', [False])

    def _focus_changed(self, _old, new):
        if not is_text_input(new):
            self._hide_keyboard()

    def eventFilter(self, watched, event):
        if event.type() not in (QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin):
            return False
        if not isinstance(watched, QWidget):
            return False
        # スクロールバーやボタンを触ったとき、フォーカスが古い入力欄に
        # 残る場合がある。次のイベント処理で新しいフォーカスを確認する。
        focus = self.app.focusWidget()
        if is_text_input(focus) and not (watched is focus or focus.isAncestorOf(watched)):
            focus.clearFocus()
            self._hide_keyboard()
        return False
