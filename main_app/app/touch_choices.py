from PySide6.QtWidgets import QComboBox, QDialog, QVBoxLayout, QPushButton, QLabel


def choose(parent, title, options, current):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(360)
    layout = QVBoxLayout(dialog)
    layout.setSpacing(10)
    layout.addWidget(QLabel(title))
    result = [None]
    for value, label in options:
        button = QPushButton(label)
        button.setMinimumHeight(54)
        button.setCheckable(True)
        button.setChecked(value == current)
        def select(_checked=False, value=value):
            result[0] = value
            dialog.accept()
        button.clicked.connect(select)
        layout.addWidget(button)
    cancel = QPushButton('キャンセル')
    cancel.setMinimumHeight(48)
    cancel.clicked.connect(dialog.reject)
    layout.addWidget(cancel)
    dialog.exec()
    return result[0]


class TouchComboBox(QComboBox):
    def showPopup(self):
        selected = choose(self.window(), self.accessibleName(), [(self.itemData(i), self.itemText(i)) for i in range(self.count())], self.currentData())
        if selected is not None:
            self.setCurrentIndex(self.findData(selected))
