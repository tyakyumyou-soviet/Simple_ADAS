from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QVBoxLayout, QPushButton, QLabel, QFrame, QScrollArea, QWidget


def choose(parent, title, options, current):
    # 同一の親ウィンドウ内に表示し、Waylandの別ウィンドウの重なり順に依存しない。
    shield = QFrame(parent)
    shield.setObjectName("choiceShield")
    shield.setStyleSheet("QFrame#choiceShield { background: rgba(0, 0, 0, 150); }")
    shield.setGeometry(parent.rect())
    shield.show()
    shield.raise_()
    dialog = QDialog(shield)
    dialog.setWindowFlags(Qt.WindowType.Widget)
    dialog.setObjectName("choiceOverlay")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setStyleSheet("QDialog#choiceOverlay { background: #111c27; border: 2px solid #76c8bd; border-radius: 12px; }")
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(360)
    layout = QVBoxLayout(dialog)
    layout.setSpacing(10)
    layout.addWidget(QLabel(title))
    result = [None]
    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setMinimumHeight(100)
    choices = QWidget()
    choices_layout = QVBoxLayout(choices)
    choices_layout.setContentsMargins(0, 0, 0, 0)
    choices_layout.setSpacing(8)
    for value, label in options:
        button = QPushButton(label)
        button.setMinimumHeight(54)
        button.setCheckable(True)
        button.setChecked(value == current)
        def select(_checked=False, value=value):
            result[0] = value
            dialog.accept()
        button.clicked.connect(select)
        choices_layout.addWidget(button)
    choices_layout.addStretch()
    scroll.setWidget(choices)
    layout.addWidget(scroll, 1)
    cancel = QPushButton('キャンセル')
    cancel.setMinimumHeight(48)
    cancel.clicked.connect(dialog.reject)
    layout.addWidget(cancel)
    dialog.resize(min(max(360, parent.width() - 80), parent.width()), min(150 + len(options) * 62, parent.height() - 16))
    dialog.move(max(0, (parent.width() - dialog.width()) // 2),
                max(0, (parent.height() - dialog.height()) // 2))
    dialog.show()
    dialog.raise_()
    try:
        dialog.exec()
    finally:
        shield.hide()
        shield.deleteLater()
    return result[0]


class TouchComboBox(QComboBox):
    def showPopup(self):
        selected = choose(self.window(), self.accessibleName(), [(self.itemData(i), self.itemText(i)) for i in range(self.count())], self.currentData())
        if selected is not None:
            self.setCurrentIndex(self.findData(selected))


def exec_embedded(dialog, parent):
    """子画面を同じ描画面に置き、背後へのタッチと潜り込みを防ぐ。"""
    shield = QFrame(parent)
    shield.setObjectName("choiceShield")
    shield.setStyleSheet("QFrame#choiceShield { background: rgba(0, 0, 0, 150); }")
    shield.setGeometry(parent.rect())
    shield.show()
    shield.raise_()
    dialog.setParent(shield)
    dialog.setWindowFlags(Qt.WindowType.Widget)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.resize(max(dialog.minimumWidth(), parent.width() - 16),
                  max(dialog.minimumHeight(), parent.height() - 16))
    dialog.move(max(0, (parent.width() - dialog.width()) // 2),
                max(0, (parent.height() - dialog.height()) // 2))
    dialog.show()
    dialog.raise_()
    try:
        return dialog.exec()
    finally:
        shield.hide()
        # 呼び出し側が保存値を読み取るまで、子画面を破棄しない。
        dialog.setParent(parent)
        shield.deleteLater()
