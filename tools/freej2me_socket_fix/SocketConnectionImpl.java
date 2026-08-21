/*
    Local smoke-test adapter for FreeJ2ME-Plus.
    It implements the MIDP SocketConnection contract over java.net.Socket.
*/
package javax.microedition.io;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Socket;

public final class SocketConnectionImpl implements SocketConnection {
    private final Socket socket;

    public SocketConnectionImpl(String url) throws IOException {
        if (url == null || !url.startsWith("socket://")) {
            throw new IOException("Unsupported socket URL: " + url);
        }
        String authority = url.substring("socket://".length());
        int parameterSeparator = authority.indexOf(';');
        if (parameterSeparator >= 0) {
            authority = authority.substring(0, parameterSeparator);
        }
        int colon = authority.lastIndexOf(':');
        if (colon <= 0 || colon == authority.length() - 1) {
            throw new IOException("Socket URL must be socket://host:port: " + url);
        }
        String host = authority.substring(0, colon);
        int port;
        try {
            port = Integer.parseInt(authority.substring(colon + 1));
        } catch (NumberFormatException exception) {
            throw new IOException("Invalid socket port in URL: " + url);
        }
        socket = new Socket();
        socket.connect(new InetSocketAddress(host, port));
    }

    public DataInputStream openDataInputStream() throws IOException {
        return new DataInputStream(socket.getInputStream());
    }

    public java.io.InputStream openInputStream() {
        try {
            return socket.getInputStream();
        } catch (IOException exception) {
            throw new IllegalStateException(exception);
        }
    }

    public DataOutputStream openDataOutputStream() {
        try {
            return new DataOutputStream(socket.getOutputStream());
        } catch (IOException exception) {
            throw new IllegalStateException(exception);
        }
    }

    public java.io.OutputStream openOutputStream() {
        try {
            return socket.getOutputStream();
        } catch (IOException exception) {
            throw new IllegalStateException(exception);
        }
    }

    public void close() {
        try {
            socket.close();
        } catch (IOException ignored) {
        }
    }

    public String getAddress() {
        return socket.getInetAddress().getHostAddress();
    }

    public String getLocalAddress() {
        return socket.getLocalAddress().getHostAddress();
    }

    public int getLocalPort() {
        return socket.getLocalPort();
    }

    public int getPort() {
        return socket.getPort();
    }

    public int getSocketOption(byte option) {
        try {
            switch (option) {
                case DELAY:
                    return socket.getTcpNoDelay() ? 1 : 0;
                case KEEPALIVE:
                    return socket.getKeepAlive() ? 1 : 0;
                case LINGER:
                    return socket.getSoLinger();
                case RCVBUF:
                    return socket.getReceiveBufferSize();
                case SNDBUF:
                    return socket.getSendBufferSize();
                default:
                    throw new IllegalArgumentException("Unknown socket option: " + option);
            }
        } catch (IOException exception) {
            throw new IllegalStateException(exception);
        }
    }

    public void setSocketOption(byte option, int value) {
        try {
            switch (option) {
                case DELAY:
                    socket.setTcpNoDelay(value != 0);
                    return;
                case KEEPALIVE:
                    socket.setKeepAlive(value != 0);
                    return;
                case LINGER:
                    socket.setSoLinger(value >= 0, value);
                    return;
                case RCVBUF:
                    socket.setReceiveBufferSize(value);
                    return;
                case SNDBUF:
                    socket.setSendBufferSize(value);
                    return;
                default:
                    throw new IllegalArgumentException("Unknown socket option: " + option);
            }
        } catch (IOException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
