import logging
import threading
import grpc
import books_pb2, books_pb2_grpc

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError
from concurrent import futures

from models import Book, Base
from utils import retry
from database import get_db_connection
from kafka_consumer import KafkaBookConsumer
from kafka.errors import KafkaError


Session = sessionmaker()
logging.basicConfig(level=logging.INFO, format='Server | %(asctime)s - %(levelname)s - %(message)s')


class BookService(books_pb2_grpc.BookServiceServicer):
    def __init__(self):
        try:
            self.Session = get_db_connection()
            logging.info("Успешное подключение к базе данных.")
        except Exception as e:
            logging.error(f"Ошибка подключения к базе данных: {e}")
            raise

    @retry(times=3, delay=1, exceptions=(OperationalError,))
    def getBookById(self, request, context):
        
        with self.Session() as session:
            book = session.query(Book).filter(Book.id==request.id).first()
            
            if book:
                return books_pb2.BookResponse(id=book.id, title=book.title, author=book.author)
            else:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('Книга не найдена')
                return books_pb2.BookResponse()
    
    @retry(times=3, delay=1, exceptions=(OperationalError,))
    def getAllBooks(self, request, context):
        
        with self.Session() as session:
            books = session.query(Book).all()

            response = books_pb2.BookListResponse()
            for book in books:
                response.books.add(id=book.id, title=book.title, author=book.author)
            return response


def serve():
    logging.info("Запуск сервиса...")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    books_pb2_grpc.add_BookServiceServicer_to_server(BookService(), server)
    server.add_insecure_port('[::]:50051')

    kafka_consumer = KafkaBookConsumer(
        topic='book_events',
        bootstrap_servers='kafka:9092'
    )
    kafka_consumer.start()

    server.start()
    logging.info("gRPC сервис запущен на порту 50051")
    server.wait_for_termination()


if __name__ == '__main__':
    serve()