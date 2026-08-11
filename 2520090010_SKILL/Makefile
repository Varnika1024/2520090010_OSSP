CC = gcc
CFLAGS = -Wall -Iinclude
SRC = src/main.c
TARGET = bin/app

all: $(TARGET)

$(TARGET): $(SRC)
	@mkdir -p bin
	$(CC) $(CFLAGS) $(SRC) -o $(TARGET)

clean:
	rm -rf bin/*

run: all
	./$(TARGET)
