package kr.talkdock.app.notifications

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class TodakMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) = PushRegistration.sync(this, token)
    override fun onMessageReceived(message: RemoteMessage) = TodakNotifications.receive(this, message.data)
}
