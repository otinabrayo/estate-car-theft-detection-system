import os

from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[import-not-found]



BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "localhost:9092"
)

TOPICS = [
    "gate.entry.v1",
    "gate.exit.v1",
    "gate.access.retry.v1",
    "gate.access.dlq.v1",
    "gate.access.processed.v1",
]


def create_topics():
    admin = AdminClient({
        "bootstrap.servers": BOOTSTRAP_SERVERS
    })

    topic_definitions = [
        NewTopic(
            topic,
            num_partitions=3,
            replication_factor=1,
            config={
                "cleanup.policy": "delete",
                "retention.ms": "604800000",
            },
        )
        for topic in TOPICS
    ]

    futures = admin.create_topics(
        topic_definitions,
        validate_only=False,
    )

    for topic, future in futures.items():
        try:
            future.result()
            print(f"[CREATED] {topic}")

        except Exception as exc:
            if "TOPIC_ALREADY_EXISTS" in str(exc):
                print(f"[EXISTS] {topic}")
            else:
                print(f"[ERROR] {topic}: {exc}")


if __name__ == "__main__":
    create_topics()
