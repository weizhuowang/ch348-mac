// SPDX-License-Identifier: GPL-2.0-or-later
// Qt 6.11.2's public QString constructor only resolves already-enumerated ports.
// Use its matching private descriptor and the framework's own copy constructor.
#include <QtCore/qlist.h>
#include <QtCore/qfile.h>
#include <QtSerialPort/qserialportglobal.h>
#include <private/qserialportinfo_p.h>
#define private public
#include <QtSerialPort/qserialportinfo.h>
#undef private
#include <QtSerialPort/QSerialPort>
#include <IOKit/serial/ioss.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <termios.h>
#include <cstdio>

static QList<QSerialPortInfo> ch348Ports()
{
    auto ports = QSerialPortInfo::availablePorts();
    for (int i = 0; i < 8; ++i) {
        QSerialPortInfoPrivate port;
        port.device = QStringLiteral("/tmp/ch348/") + QString::number(i);
        if (!QFile::exists(port.device))
            continue;
        port.portName = QStringLiteral("tty.CH348-") + QString::number(i);
        port.description = QStringLiteral("CH348 UART ") + QString::number(i);
        port.manufacturer = QStringLiteral("WCH");
        port.hasVendorIdentifier = port.hasProductIdentifier = true;
        port.vendorIdentifier = 0x1a86;
        port.productIdentifier = 0x55d9;
        ports.append(QSerialPortInfo(port));
    }
    if (qEnvironmentVariableIsSet("CH348_DIAGNOSTICS")) {
        for (const auto &port : ports)
            fprintf(stderr, "availablePorts name=%s location=%s\n",
                    qPrintable(port.portName()), qPrintable(port.systemLocation()));
    }
    return ports;
}

// Darwin PTYs accept numeric speeds via tcsetattr, but reject IOSSIOSPEED.
// Examine only this request and only PTYs currently published by our bridge.
extern "C" int ch348Speed(int fd, unsigned long request, const void *arg)
{
    struct stat actual{}, target{};
    if (arg && fstat(fd, &actual) == 0 && S_ISCHR(actual.st_mode)) {
        for (int i = 0; i < 8; ++i) {
            char path[32];
            snprintf(path, sizeof(path), "/tmp/ch348/%d", i);
            if (stat(path, &target) || actual.st_rdev != target.st_rdev)
                continue;
            // On macOS, Qt 6.11 passes the requested rate as a pointer to qint32.
            speed_t rate = *static_cast<const quint32 *>(arg);
            if (rate < 1200 || rate > 4000000) {
                errno = EINVAL;
                return -1;
            }
            termios settings{};
            if (tcgetattr(fd, &settings) || cfsetspeed(&settings, rate))
                return -1;
            return tcsetattr(fd, TCSANOW, &settings);
        }
    }
    return ioctl(fd, request, arg);
}

extern "C" void qtSetName(QSerialPort *, const QString &)
    __asm__("__ZN11QSerialPort11setPortNameERK7QString");

static void setName(QSerialPort *port, const QString &name)
{
    QString resolved = name;
    for (int i = 0; i < 8; ++i) {
        const QString alias = QStringLiteral("tty.CH348-") + QString::number(i);
        if (name == alias || name == QStringLiteral("/dev/") + alias) {
            resolved = QStringLiteral("/tmp/ch348/") + QString::number(i);
            break;
        }
    }
    if (qEnvironmentVariableIsSet("CH348_DIAGNOSTICS")) {
        fprintf(stderr, "setPortName %s -> %s\n", qPrintable(name), qPrintable(resolved));
    }
    qtSetName(port, resolved);
}

// Qt derives portName() from the path passed to setPortName(). Wizard also
// keys its connected-device polling by the public, enumerated port name.
extern QString qtPortName(const QSerialPort *) __asm__("__ZNK11QSerialPort8portNameEv");

static QString portNameForWizard(const QSerialPort *port)
{
    const QString name = qtPortName(port);
    const QString prefix = QStringLiteral("/tmp/ch348/");
    if (name.size() == prefix.size() + 1 && name.startsWith(prefix)
        && name.back() >= u'0' && name.back() <= u'7')
        return QStringLiteral("tty.CH348-") + name.back();
    return name;
}

extern "C" int ch348Ioctl(int, unsigned long, ...);
static_assert(IOSSIOSPEED == 0x80085402UL);
__attribute__((used, section("__DATA,__interpose")))
static const struct { const void *replacement; const void *original; } overrides[] = {
    { (const void *)ch348Ports, (const void *)QSerialPortInfo::availablePorts },
    { (const void *)portNameForWizard, (const void *)qtPortName },
    { (const void *)setName, (const void *)qtSetName },
    { (const void *)ch348Ioctl, (const void *)ioctl }
};
